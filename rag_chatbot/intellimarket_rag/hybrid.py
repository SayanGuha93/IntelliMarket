"""Exact constraints, BM25 and dense candidates, fused at the product level."""

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from threading import Lock

from .ingest import key
from .attributes import FACETS, attribute_sql
from .paths import catalog_path, index_path, project_root
from .query import QueryError, normalized, validate
from .semantic import PRICE_NOTICE, SemanticSearch, open_catalog


STOP_WORDS = set("""
    a an and are as at be by can find for from has have i in is it me my of on
    or pair please product products show sold some such suitable that the their
    to use want wear with would you part need which there
""".split())
INFLECTIONS = {
    "clothes": "clothing", "trousers": "pants", "bags": "bag", "headphones": "headphone",
    "womens": "women", "mens": "men", "women's": "women", "men's": "men",
    "fastens": "fasten", "fastening": "fasten", "fastened": "fasten",
    "stretchy": "stretch", "stretchable": "stretch", "toughened": "tempered",
    "floral": "flower", "flowers": "flower", "fitted": "fit", "supplies": "supply",
}


def words(text):
    return re.findall(r"[^\W_]+(?:'[^\W_]+)?", normalized(text))


def evidence_terms(text):
    return {INFLECTIONS.get(term, term[:-1] if len(term) > 4 and term.endswith("s") else term)
            for term in words(text) if term not in STOP_WORDS}


def keyword_expression(text):
    tokens = list(dict.fromkeys(term for term in words(text) if term not in STOP_WORDS))
    tokens = tokens or words(text)
    alternatives = []
    for term in tokens[:40]:
        alternatives.extend(re.findall(r"[^\W_]+", term.removesuffix("'s")))
        canonical = INFLECTIONS.get(term)
        if canonical:
            alternatives.append(canonical)
    return " OR ".join(f'"{term}"' for term in dict.fromkeys(alternatives))


def reciprocal_rank_fusion(rankings, *, k=60, weights=None):
    if not rankings or not 1 <= k <= 1000:
        raise ValueError("RRF k must be between 1 and 1,000.")
    weights = [1.0] * len(rankings) if weights is None else list(weights)
    if len(weights) != len(rankings) or any(not 0 < value <= 10 for value in weights):
        raise ValueError("Each ranking needs a positive fusion weight up to 10.")
    scores = {}
    for ranking, weight in zip(rankings, weights):
        for rank, product_id in enumerate(dict.fromkeys(ranking), 1):
            scores[product_id] = scores.get(product_id, 0) + weight / (k + rank)
    return scores


def sql_constraints(query):
    clauses, values = [], []
    for column, value in (("platform", query.platform), ("brand_key", query.brand),
                          ("colour_key", query.colour), ("name_key", query.name),
                          ("source_id", query.product_id)):
        if value is not None:
            clauses.append(f"p.{column} = ?")
            value = key(" ".join(value.split())) if column.endswith("_key") else value
            if column == "source_id":
                value = re.sub(r"(?<=\d)\.0+$", "", value) if re.fullmatch(r"\d+\.0+", value) else value.upper()
            values.append(value)
    if query.category is not None:
        clauses.append("EXISTS (SELECT 1 FROM categories c WHERE c.product_id=p.id AND c.category_key=?)")
        values.append(key(" ".join(query.category.split())))
    for field in FACETS:
        value = getattr(query, field)
        if value is not None:
            predicate, params = attribute_sql(field, value)
            clauses.append(predicate)
            values.extend(params)
    price = "retail_price_minor" if query.price_field == "retail" else "price_minor"
    for field, column, scale in (("price", price, 100), ("rating", "rating", None),
                                 ("count", "rating_count", 1)):
        for suffix, operator in (("_min", ">"), ("_max", "<")):
            bound = getattr(query, field + suffix)
            if bound:
                operator += "=" if bound.inclusive else ""
                clauses.append(f"p.{column} {operator} ?")
                values.append(int(bound.value * scale) if scale else float(bound.value))
    sort = {
        None: "p.name_key, p.id", "name": "p.name_key, p.id",
        "price-asc": f"p.{price} IS NULL, p.{price}, p.id",
        "price-desc": f"p.{price} IS NULL, p.{price} DESC, p.id",
        "rating-desc": "p.rating IS NULL, p.rating DESC, p.id",
        "count-desc": "p.rating_count IS NULL, p.rating_count DESC, p.id",
    }[query.sort]
    return " AND ".join(clauses) or "1", values, sort


@dataclass(frozen=True)
class RetrievalConfig:
    keyword_pool: int = 100
    semantic_pool: int = 100
    rrf_k: int = 30
    keyword_weight: float = 1.0
    semantic_weight: float = 1.0
    rerank_pool: int = 40

    def __post_init__(self):
        if (not 1 <= self.keyword_pool <= 500 or not 1 <= self.semantic_pool <= 500
                or not 1 <= self.rerank_pool <= 200):
            raise ValueError("Candidate pools must be positive and within supported limits.")
        reciprocal_rank_fusion([[], []], k=self.rrf_k,
                               weights=[self.keyword_weight, self.semantic_weight])


class HybridSearch:
    def __init__(self, root=None, *, device="cpu", threads=6, semantic=None, catalog=None, index_dir=None):
        self.root = project_root(root)
        self.catalog = catalog_path(self.root, catalog=catalog)
        self.index_dir = index_path(self.root, index_dir=index_dir)
        self.device = device
        self.threads = threads
        self._semantic = semantic
        self._semantic_lock = Lock()

    @property
    def initialization_ms(self):
        return getattr(self._semantic, "initialization_ms", {}).copy()

    @property
    def semantic(self):
        with self._semantic_lock:
            if self._semantic is None:
                self._semantic = SemanticSearch(self.root, device=self.device, threads=self.threads,
                                                catalog=self.catalog, index_dir=self.index_dir)
        return self._semantic

    def search(self, query, *, mode="hybrid", top_k=10, config=RetrievalConfig()):
        query = validate(query)
        if query.comparison:
            raise QueryError("Use the comparison service for this intent.")
        if mode not in {"fts", "semantic", "hybrid", "rerank"} or not 1 <= top_k <= 100:
            raise ValueError("Choose a retrieval mode and top-k from 1 to 100.")
        where, values, order = sql_constraints(query)
        with closing(open_catalog(self.catalog)) as connection:
            if not query.terms or query.product_id:
                rows = connection.execute(
                    f"SELECT p.* FROM products p WHERE {where} ORDER BY {order} LIMIT ?",
                    (*values, top_k),
                )
                return self.results(connection, [dict(row) for row in rows], {}, {})
            has_extra_filters = where not in {"1", "p.platform = ?"}
            eligible = None
            if has_extra_filters and mode != "fts":
                eligible = {row[0] for row in connection.execute(
                    f"SELECT p.id FROM products p WHERE {where}", values
                )}
                if not eligible:
                    return []
            keyword = []
            expression = keyword_expression(query.terms)
            if mode != "semantic" and expression:
                keyword = [row[0] for row in connection.execute(
                    f"""SELECT p.id FROM product_fts JOIN products p ON p.id=product_fts.rowid
                        WHERE product_fts MATCH ? AND ({where})
                        ORDER BY bm25(product_fts, 5, 2, 2, 1, 1, 2, 1, 4), p.id LIMIT ?""",
                    (expression, *values, max(config.keyword_pool, top_k)),
                )]
            dense = {}
            if mode != "fts":
                dense = self.semantic.ranked_chunks(
                    query.terms, top_k=max(config.semantic_pool, top_k), platform=query.platform,
                    eligible=eligible,
                )
            weights = [config.keyword_weight, config.semantic_weight]
            scores = reciprocal_rank_fusion([keyword, dense], k=config.rrf_k, weights=weights)
            explicit = normalized(query.terms)
            if mode in {"hybrid", "rerank"}:
                exact_titles = connection.execute(
                    f"SELECT p.id FROM products p WHERE p.name_key=? AND ({where}) ORDER BY {order} LIMIT ?",
                    (explicit, *values, top_k),
                )
                for row in exact_titles:
                    scores.setdefault(row[0], 0.0)
            if not scores:
                return []
            ranked = sorted(scores, key=lambda product_id: (-scores[product_id], product_id))
            if mode == "fts":
                ranked = keyword
            elif mode == "semantic":
                ranked = list(dense)
            ids = ",".join("?" for _ in ranked)
            products = {row["id"]: dict(row) for row in connection.execute(
                f"SELECT p.* FROM products p WHERE p.id IN ({ids}) AND ({where}) ORDER BY {order}",
                (*ranked, *values),
            )}
            if query.sort:
                ranked = list(products)
            else:
                if mode == "rerank":
                    ranked = self.rerank(query.terms, ranked, products, dense, scores, config.rerank_pool)
                if mode.startswith("hybrid") or mode == "rerank":
                    ranked.sort(key=lambda product_id: normalized(products[product_id]["name"]) != explicit)
            if dense:
                self.semantic._check_catalog_version()
            return self.results(connection, [products[pid] for pid in ranked[:top_k]], scores, dense)

    @staticmethod
    def rerank(query, ranked, products, dense, scores, pool):
        """Blend rank and token coverage in the top fused candidates, without a model dependency."""
        terms = evidence_terms(query)
        if not terms:
            return ranked
        score_scale = scores[ranked[0]] or 1.0

        def score(product_id):
            product = products[product_id]
            title = evidence_terms(product["name"])
            evidence = evidence_terms(" ".join(value for value in (
                product["brand"], product["description"], product["attributes"],
                product["category_path"], dense.get(product_id, {}).get("text"),
            ) if value))
            coverage = (0.6 * len(terms & title) + 0.4 * len(terms & (title | evidence))) / len(terms)
            return 0.6 * (scores[product_id] / score_scale) + 0.4 * coverage

        return sorted(ranked[:pool], key=score, reverse=True) + ranked[pool:]

    @staticmethod
    def results(connection, products, scores, dense):
        if not products:
            return []
        ids = [product["id"] for product in products]
        placeholders = ",".join("?" for _ in ids)
        sources = {}
        for row in connection.execute(f"""
            SELECT product_id, record_number, source_record_id,
                   json_extract(normalized_json, '$.product_url') AS product_url,
                   json_extract(normalized_json, '$.observed_at') AS observed_at
            FROM source_records WHERE status='accepted' AND product_id IN ({placeholders})
            ORDER BY record_number""", ids):
            record = dict(row)
            sources.setdefault(record.pop("product_id"), []).append(record)
        return [{
            "product": product, "fusion_score": scores.get(product["id"]),
            "similarity": 1.0 - dense[product["id"]]["_distance"] if product["id"] in dense else None,
            "source": {"file": f"{product['platform']}.csv", "records": sources[product["id"]]},
            "price_notice": PRICE_NOTICE,
        } for product in products]
