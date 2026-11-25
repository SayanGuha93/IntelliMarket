"""SQLite build and allowlisted, parameterized catalog queries."""

import json
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from decimal import InvalidOperation
from time import perf_counter
from uuid import uuid4

from .ingest import clean, key, normalize, number, records, sha256
from .paths import open_catalog, project_root


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL CHECK (platform IN ('flipkart', 'myntra')),
    source_id TEXT NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    brand TEXT, brand_key TEXT,
    colour TEXT, colour_key TEXT,
    category_path TEXT NOT NULL,
    category_basis TEXT,
    description TEXT,
    attributes TEXT NOT NULL,
    notes TEXT NOT NULL,
    price_minor INTEGER CHECK (price_minor >= 0),
    retail_price_minor INTEGER CHECK (retail_price_minor >= 0),
    rating REAL CHECK (rating BETWEEN 0 AND 5),
    overall_rating REAL CHECK (overall_rating BETWEEN 0 AND 5),
    rating_count INTEGER CHECK (rating_count >= 0),
    observed_at TEXT, product_url TEXT, image_url TEXT,
    price_field TEXT NOT NULL,
    conflicts TEXT NOT NULL,
    UNIQUE (platform, source_id)
);
CREATE TABLE source_records (
    platform TEXT NOT NULL,
    record_number INTEGER NOT NULL,
    source_record_id TEXT,
    product_id INTEGER REFERENCES products(id),
    status TEXT NOT NULL CHECK (status IN ('accepted', 'duplicate', 'excluded')),
    reason TEXT,
    duplicate_of INTEGER,
    raw_json TEXT NOT NULL,
    normalized_json TEXT,
    PRIMARY KEY (platform, record_number),
    FOREIGN KEY (platform, duplicate_of) REFERENCES source_records(platform, record_number),
    CHECK ((status = 'excluded') = (product_id IS NULL)),
    CHECK ((status = 'duplicate') = (duplicate_of IS NOT NULL))
);
CREATE TABLE categories (
    product_id INTEGER NOT NULL REFERENCES products(id),
    category_key TEXT NOT NULL,
    PRIMARY KEY (category_key, product_id)
) WITHOUT ROWID;
CREATE TABLE build_metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX products_source ON products(source_id);
CREATE INDEX products_name ON products(name_key);
CREATE INDEX products_brand ON products(brand_key);
CREATE INDEX products_colour ON products(colour_key);
CREATE INDEX products_price ON products(price_minor);
CREATE INDEX products_retail_price ON products(retail_price_minor);
CREATE INDEX products_rating ON products(rating);
CREATE INDEX source_records_product ON source_records(product_id, record_number);
CREATE VIRTUAL TABLE product_fts USING fts5(
    name, brand, categories, colour, description, attributes, notes, identifiers,
    tokenize='unicode61 remove_diacritics 2'
);
"""

SORTS = {
    "name": "p.name_key ASC, p.id",
    "price-asc": "p.{price} IS NULL, p.{price} ASC, p.id",
    "price-desc": "p.{price} IS NULL, p.{price} DESC, p.id",
    "rating-desc": "p.rating IS NULL, p.rating DESC, p.id",
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def consensus(group):
    """Keep agreed facts, recording divergent nonmissing values with their rows."""
    fields = group[0][1]
    product, conflicts = {}, {}
    attribute_keys = sorted({label for _, row in group for label in row["attributes"]})
    product["attributes"] = {}
    for field in fields:
        if field in {"source_record_id", "attributes"}:
            continue
        values = {}
        for record_number, row in group:
            value = row[field]
            if value is not None and value != [] and value != {}:
                values.setdefault(encoded(value), [value, []])[1].append(record_number)
        if len(values) == 1:
            product[field] = next(iter(values.values()))[0]
        else:
            product[field] = None
            if values:
                conflicts[field] = [
                    {"value": value, "records": rows} for value, rows in values.values()
                ]
    for label in attribute_keys:
        values = {}
        for record_number, row in group:
            value = row["attributes"].get(label)
            if value:
                values.setdefault(encoded(sorted(set(value))), [value, []])[1].append(record_number)
        if len(values) == 1:
            product["attributes"][label] = next(iter(values.values()))[0]
        else:
            conflicts[f"attributes.{label}"] = [
                {"value": value, "records": rows} for value, rows in values.values()
            ]
    return product, conflicts


def insert_product(connection, platform, source_id, group):
    product, conflicts = consensus(group)
    # A title is necessary for lookup and display, even when source titles disagree.
    # Keep the first observed title as the display label and flag the alternatives.
    name = product["name"] or group[0][1]["name"]
    categories = product["categories"] or []
    attributes = product["attributes"] or {}
    notes = product["notes"] or []
    price_field = "discounted_price" if platform == "flipkart" else "price"
    cursor = connection.execute(
        """INSERT INTO products (
               platform, source_id, name, name_key, brand, brand_key, colour, colour_key,
               category_path, category_basis, description, attributes, notes, price_minor, retail_price_minor,
               rating, overall_rating, rating_count, observed_at, product_url, image_url,
               price_field, conflicts
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (platform, source_id, name, key(name), product["brand"], key(product["brand"]),
         product["colour"], key(product["colour"]), encoded(categories), product["category_basis"],
         product["description"], encoded(attributes), encoded(notes), product["price_minor"],
         product["retail_price_minor"], product["rating"], product["overall_rating"],
         product["rating_count"], product["observed_at"], product["product_url"],
         product["image_url"], price_field, encoded(conflicts)),
    )
    product_id = cursor.lastrowid
    connection.executemany(
        "INSERT INTO categories VALUES (?, ?)",
        ((product_id, category) for category in sorted({key(value) for value in categories})),
    )
    connection.execute(
        "INSERT INTO product_fts(rowid, name, brand, categories, colour, description, attributes, notes, identifiers) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (product_id, " ".join(dict.fromkeys(row["name"] for _, row in group)), product["brand"],
         " ".join(categories), product["colour"], product["description"],
         " ".join(f"{label} {' '.join(values)}" for label, values in attributes.items()),
         " ".join(notes), source_id),
    )
    return product_id, conflicts


def ingest_source(connection, path, platform):
    counts, missing, issues, conflicts = Counter(), Counter(), Counter(), Counter()
    groups = defaultdict(list)
    source_rows = []
    seen = {}
    for record_number, raw in records(path, platform):
        counts["raw"] += 1
        missing.update({field: int(clean(value) is None) for field, value in raw.items()})
        fingerprint = encoded(raw)
        normalized = None
        duplicate_of = None
        if all(not value.strip() for value in raw.values()):
            status, reason = "excluded", "empty_payload"
        else:
            normalized = normalize(platform, raw, issues)
            if not normalized["source_id"] or not normalized["source_record_id"] or not normalized["name"]:
                status, reason = "excluded", "missing_or_invalid_identity"
            elif fingerprint in seen:
                status, reason = "duplicate", "exact_payload"
                duplicate_of = seen[fingerprint]
            else:
                status, reason = "accepted", None
                seen[fingerprint] = record_number
                groups[normalized["source_id"]].append((record_number, normalized))
        counts[status] += 1
        if status == "excluded":
            counts[reason] += 1
        source_rows.append((record_number, raw, normalized, status, reason, duplicate_of))

    ids = {}
    for source_id, group in groups.items():
        ids[source_id], found = insert_product(connection, platform, source_id, group)
        conflicts.update(found.keys())
        counts["products_with_conflicts"] += bool(found)
        counts["products_with_multiple_accepted_records"] += len(group) > 1
    connection.executemany(
        "INSERT INTO source_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            (platform, row, normalized and normalized["source_record_id"],
             ids[normalized["source_id"]] if status != "excluded" else None,
             status, reason, duplicate_of, encoded(raw),
             encoded(normalized) if normalized else None)
            for row, raw, normalized, status, reason, duplicate_of in source_rows
        ),
    )
    normalized_missing = {}
    for field in ("brand", "colour", "price_minor", "retail_price_minor", "rating",
                  "overall_rating", "rating_count", "description", "observed_at",
                  "product_url", "image_url", "category_path", "attributes"):
        # Column names come from the fixed internal list above.
        normalized_missing[field] = connection.execute(
            f"SELECT count(*) FROM products WHERE platform = ? AND ({field} IS NULL OR {field} IN ('[]', '{{}}') )",
            (platform,),
        ).fetchone()[0]
    return {
        "source_file": path.name,
        "counts": {**dict.fromkeys(("raw", "accepted", "excluded", "duplicate"), 0),
                   **counts, "products": len(ids)},
        "source_missing_by_field": dict(missing),
        "catalog_missing_by_field": normalized_missing,
        "normalization_issues": dict(issues),
        "conflicts_by_field": dict(conflicts),
    }


@contextmanager
def catalog_staging(artifacts):
    # Files moved out of a private Windows temp directory can retain its ACL.
    # A normal directory here inherits the permissions of the destination.
    staging = artifacts / f"build-{uuid4().hex}"
    staging.mkdir()
    try:
        yield staging
    finally:
        shutil.rmtree(staging)


def build(root=None):
    root = project_root(root)
    start = perf_counter()
    platforms = ("flipkart", "myntra")
    inputs = {source: root / "data" / f"{source}.csv" for source in platforms}
    before = {source: sha256(path) for source, path in inputs.items()}
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    target = artifacts / "catalog.sqlite3"
    with catalog_staging(artifacts) as staging:
        db = staging / target.name
        with closing(sqlite3.connect(db)) as connection, connection:
            connection.executescript(SCHEMA)
            sources = {
                source: ingest_source(connection, inputs[source], source) for source in platforms
            }
            after = {source: sha256(path) for source, path in inputs.items()}
            if before != after:
                raise RuntimeError("An input CSV changed during ingestion")
            sizes = {
                table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("products", "source_records", "categories", "product_fts")
            }
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if (integrity != "ok" or foreign_key_violations
                    or sizes["products"] != sizes["product_fts"]
                    or sizes["source_records"] != sum(s["counts"]["raw"] for s in sources.values())):
                raise RuntimeError("Catalog validation failed")
            report = {
                "sources": sources, "sha256_before": before, "sha256_after": after,
                "tables": sizes, "integrity_check": integrity,
                "foreign_key_violations": len(foreign_key_violations),
                "sqlite_version": sqlite3.sqlite_version,
                "price_scale": 100, "currency": None,
            }
            connection.execute("INSERT INTO build_metadata VALUES (?, ?)", ("ingestion", encoded(report)))
        report["database_bytes"] = db.stat().st_size
        report["elapsed_seconds"] = round(perf_counter() - start, 3)
        report_path = staging / "ingestion_report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        db.replace(target)
        report_path.replace(artifacts / report_path.name)
    return report


def search(db, *, keywords=None, name=None, platform=None, brand=None, category=None,
           colour=None, min_price=None, max_price=None, min_rating=None, max_rating=None,
           product_id=None, price_field="recorded", sort="name", limit=20, offset=0):
    if (sort not in SORTS and sort != "relevance") or not 1 <= limit <= 200 or offset < 0:
        raise ValueError("Invalid sort, limit, or offset")
    if price_field not in {"recorded", "retail"}:
        raise ValueError("Invalid price field")
    if platform is not None and platform not in {"flipkart", "myntra"}:
        raise ValueError("Invalid platform")
    clauses, params = [], []
    join = ""
    tokens = re.findall(r"[^\W_]+", keywords or "", flags=re.UNICODE)
    if keywords is not None and not tokens:
        raise ValueError("Keyword query must contain letters or numbers")
    if tokens:
        join = "JOIN product_fts ON product_fts.rowid = p.id"
        clauses.append("product_fts MATCH ?")
        params.append(" AND ".join(f'"{token}"' for token in tokens))
    if name is not None:
        clauses.append("instr(p.name_key, ?) > 0")
        params.append(key(name))
    for column, value in (("platform", platform), ("brand_key", brand), ("colour_key", colour),
                          ("source_id", product_id)):
        if value is not None:
            clauses.append(f"p.{column} = ?")
            params.append(key(value) if column.endswith("_key") else value)
    if category is not None:
        clauses.append("EXISTS (SELECT 1 FROM categories c WHERE c.product_id = p.id AND c.category_key = ?)")
        params.append(key(category))
    price_column = "retail_price_minor" if price_field == "retail" else "price_minor"
    try:
        for column, low, high, scale in (
            (price_column, min_price, max_price, 100),
            ("rating", min_rating, max_rating, None),
        ):
            bounds = [
                None if value is None else number(
                    str(value), scale=scale or 1, integral=scale is not None,
                    maximum=None if scale else 5,
                )
                for value in (low, high)
            ]
            if None not in bounds and bounds[0] > bounds[1]:
                raise ValueError("Minimum exceeds maximum")
            for operator, value in zip((">=", "<="), bounds):
                if value is not None:
                    clauses.append(f"p.{column} {operator} ?")
                    params.append(value)
    except InvalidOperation as error:
        raise ValueError("Invalid numeric bound") from error
    if sort == "relevance" and not tokens:
        raise ValueError("Relevance sorting requires keywords")
    order = "bm25(product_fts), p.id" if sort == "relevance" else SORTS[sort].format(price=price_column)
    where = " AND ".join(clauses) or "1"
    with closing(open_catalog(db)) as connection:
        return [dict(row) for row in connection.execute(
            f"SELECT p.* FROM products p {join} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )]
