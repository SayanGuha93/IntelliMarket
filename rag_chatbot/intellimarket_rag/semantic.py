"""Build and search an exact, persistent semantic index over the SQLite catalog."""

import json
import os
import re
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import uuid4

from .documents import chunk_document, product_document
from .ingest import sha256
from .paths import catalog_path, index_path, open_catalog, project_root


MODEL = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
DIMENSIONS = 384
QUERY_PROMPT = "Represent this sentence for searching relevant passages: "
CONFIG = {"metric": "cosine", "search": "exact", "chunk_tokens": 224, "document_version": 1}
PRICE_NOTICE = (
    "Dataset-recorded historical prices. Flipkart crawl: 2015–2016. "
    "Myntra observation date unspecified. Current prices and availability are unverified."
)
PLATFORMS = {"flipkart", "myntra"}
# More than two native 1,000-ID scans are slower on this catalog than a cached projection.
BROAD_FILTER_SIZE = 2000


def file_identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def load_model(root, device, threads):
    cache = root / "artifacts" / "model-cache"
    os.environ.setdefault("HF_HOME", str(cache))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    import torch
    from sentence_transformers import SentenceTransformer

    if threads < 1:
        raise ValueError("Thread count must be positive")
    torch.set_num_threads(threads)
    snapshot = cache / "snapshots" / REVISION
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise ValueError("CUDA was requested, but CUDA is unavailable in this environment")
    model = SentenceTransformer(
        str(snapshot) if (snapshot / "model.safetensors").is_file() else MODEL,
        revision=REVISION, cache_folder=str(cache), device=device,
        model_kwargs={"use_safetensors": True}, trust_remote_code=False,
    )
    if model.get_sentence_embedding_dimension() != DIMENSIONS:
        raise RuntimeError("Unexpected embedding dimensions")
    if CONFIG["chunk_tokens"] + model.tokenizer.num_special_tokens_to_add() > model.max_seq_length:
        raise RuntimeError("Chunk budget exceeds model context length")
    return model


def vector_root(root=None, *, index_dir=None):
    return index_path(root, index_dir=index_dir)


def active_index(root=None, *, index_dir=None):
    store = vector_root(root, index_dir=index_dir)
    build_id = (store / "active.json").read_text(encoding="utf-8")
    build_id = json.loads(build_id)["build_id"]
    if not re.fullmatch(r"[a-f0-9]{32}", build_id):
        raise ValueError("Invalid active index identifier")
    path = store / build_id
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if manifest["build_id"] != build_id:
        raise ValueError("Active index and manifest disagree")
    return path, manifest


def catalog_identity(root=None, *, catalog=None):
    catalog = catalog_path(root, catalog=catalog)
    with closing(open_catalog(catalog)) as connection:
        record = connection.execute(
            "SELECT value FROM build_metadata WHERE name = 'ingestion'"
        ).fetchone()
        if record is None:
            raise ValueError("Missing Phase 2 ingestion metadata")
        metadata = json.loads(record[0])
        count = connection.execute("SELECT count(*) FROM products").fetchone()[0]
    return {
        "dataset_checksums": metadata["sha256_after"],
        "catalog_sha256": sha256(catalog), "product_count": count,
        "model": MODEL, "revision": REVISION, "dimensions": DIMENSIONS, "config": CONFIG,
    }


def product_chunks(connection, tokenizer):
    products = connection.execute("SELECT * FROM products ORDER BY id")
    sources = connection.execute("""
        SELECT product_id, record_number, source_record_id FROM source_records
        WHERE status = 'accepted' ORDER BY product_id, record_number
    """)
    source = sources.fetchone()
    for product in products:
        source_rows, source_ids = [], []
        while source is not None and source["product_id"] == product["id"]:
            source_rows.append(source["record_number"])
            source_ids.append(source["source_record_id"])
            source = sources.fetchone()
        if not source_rows:
            raise RuntimeError(f"Catalog product {product['id']} has no source record")
        title, sections = product_document(product, source_ids)
        for ordinal, text in enumerate(chunk_document(tokenizer, title, sections, CONFIG["chunk_tokens"])):
            yield {
                "chunk_id": f"{product['id']}:{ordinal}", "product_id": product["id"],
                "platform": product["platform"], "source_id": product["source_id"],
                "source_records": source_rows, "text": text,
            }


def index_table(path):
    import lancedb

    if not (path / "lancedb" / "chunks.lance").is_dir():
        raise FileNotFoundError("Active LanceDB table files are missing")
    return lancedb.connect(str(path / "lancedb")).open_table("chunks")


def validate_index(path, manifest):
    table = index_table(path)
    schema = table.schema
    if (table.count_rows() != manifest["vector_count"]
            or schema.field("vector").type.list_size != DIMENSIONS):
        raise ValueError("Vector index row count or dimensions disagree with the manifest")
    return table


def build_index(root=None, *, device="auto", batch_size=48, threads=6, progress=None,
                catalog=None, index_dir=None):
    import lancedb
    import numpy as np
    import psutil
    import pyarrow as pa

    if not 1 <= batch_size <= 256:
        raise ValueError("Batch size must be between 1 and 256")
    started = perf_counter()
    root = project_root(root)
    catalog = catalog_path(root, catalog=catalog)
    identity = catalog_identity(root, catalog=catalog)
    try:
        previous_path, previous = active_index(root, index_dir=index_dir)
        if all(previous.get(field) == value for field, value in identity.items()):
            validate_index(previous_path, previous)
            return {**previous, "reused": True}
    except (FileNotFoundError, ValueError, KeyError):
        pass

    model = load_model(root, device, threads)
    store = vector_root(root, index_dir=index_dir)
    store.mkdir(parents=True, exist_ok=True)
    build_id = uuid4().hex
    path = store / build_id
    process = psutil.Process()
    vector_schema = pa.schema([
        ("chunk_id", pa.string()), ("product_id", pa.int64()), ("platform", pa.string()),
        ("source_id", pa.string()), ("source_records", pa.list_(pa.int32())),
        ("text", pa.string()), ("vector", pa.list_(pa.float32(), DIMENSIONS)),
    ])
    table = lancedb.connect(str(path / "lancedb")).create_table("chunks", schema=vector_schema)
    rows, indexed_products, inferred, count = [], set(), 0, 0
    cache = {}
    peak_rss = process.memory_info().rss

    def flush():
        nonlocal count, inferred, peak_rss
        missing = list(dict.fromkeys(row["text"] for row in rows if row["text"] not in cache))
        if missing:
            vectors = model.encode(
                missing, batch_size=batch_size, normalize_embeddings=True,
                convert_to_numpy=True, show_progress_bar=False,
            )
            if vectors.shape != (len(missing), DIMENSIONS) or not np.isfinite(vectors).all():
                raise RuntimeError("Invalid embeddings returned by the model")
            cache.update(zip(missing, vectors))
            inferred += len(missing)
        for row in rows:
            row["vector"] = cache[row["text"]].tolist()
            indexed_products.add(row["product_id"])
        table.add(pa.Table.from_pylist(rows, schema=vector_schema))
        count += len(rows)
        rows.clear()
        memory = process.memory_info()
        peak_rss = max(peak_rss, getattr(memory, "peak_wset", memory.rss))
        if progress:
            progress(len(indexed_products), identity["product_count"], count, perf_counter() - started)

    with closing(open_catalog(catalog)) as connection:
        for row in product_chunks(connection, model.tokenizer):
            rows.append(row)
            if len(rows) == batch_size * 8:
                flush()
        if rows:
            flush()
    if (len(indexed_products) != identity["product_count"]
            or count != table.count_rows() or not count
            or catalog_identity(root, catalog=catalog) != identity):
        raise RuntimeError("Index coverage or catalog identity changed during indexing")
    manifest = {
        **identity, "build_id": build_id, "document_count": len(indexed_products),
        "chunk_count": count, "vector_count": count, "unique_embeddings_computed": inferred,
        "built_at_utc": datetime.now(timezone.utc).isoformat(), "device": str(model.device),
        "batch_size": batch_size, "threads": threads, "peak_process_bytes": peak_rss,
        "vector_database_bytes": sum(file.stat().st_size for file in (path / "lancedb").rglob("*") if file.is_file()),
        "elapsed_seconds": round(perf_counter() - started, 3),
    }
    if model.device.type == "cuda":
        import torch

        manifest["peak_cuda_allocated_bytes"] = torch.cuda.max_memory_allocated(model.device)
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    validate_index(path, manifest)
    pointer_path = store / f".active-{build_id}.tmp"
    try:
        with pointer_path.open("x", encoding="utf-8") as pointer:
            json.dump({"build_id": build_id}, pointer)
        os.replace(pointer_path, store / "active.json")
    finally:
        pointer_path.unlink(missing_ok=True)
    return {**manifest, "reused": False}


class SemanticSearch:
    """Keep the model and validated stores warm across multiple queries."""

    def __init__(self, root=None, *, device="auto", threads=6, catalog=None, index_dir=None):
        started = perf_counter()
        root = project_root(root)
        path, self.manifest = active_index(root, index_dir=index_dir)
        self.catalog = catalog_path(root, catalog=catalog)
        self.catalog_version = file_identity(self.catalog)
        identity = catalog_identity(root, catalog=self.catalog)
        if any(self.manifest.get(field) != value for field, value in identity.items()):
            raise ValueError("The active vector index does not match the catalog. Rebuild the index.")
        self._check_catalog_version()
        checked = perf_counter()
        self.table = validate_index(path, self.manifest)
        opened = perf_counter()
        self.model = load_model(root, device, threads)
        self._filtered_vectors = None
        self._query_lock = Lock()
        self.initialization_ms = {
            "catalog_and_manifest": (checked - started) * 1000,
            "lancedb_open": (opened - checked) * 1000,
            "embedding_model_load": (perf_counter() - opened) * 1000,
        }

    def _check_catalog_version(self):
        if file_identity(self.catalog) != self.catalog_version:
            raise ValueError("Catalog changed during this search session. Restart the service with a matching index.")

    def search(self, query, *, top_k=10, platform=None):
        query = query.strip()
        if not query or not 1 <= top_k <= 100 or (platform is not None and platform not in PLATFORMS):
            raise ValueError("Provide a query, top-k from 1 to 100, and a valid platform")
        self._check_catalog_version()
        winners = self.ranked_chunks(query, top_k=top_k, platform=platform)
        if not winners:
            return []
        return self.hydrate(winners)

    def ranked_chunks(self, query, *, top_k, platform=None, eligible=None):
        # Share the encoder and lazy broad-filter projection safely across API workers.
        with self._query_lock:
            return self._ranked_chunks(query, top_k=top_k, platform=platform, eligible=eligible)

    def _ranked_chunks(self, query, *, top_k, platform, eligible):
        self._check_catalog_version()
        embedding = self.model.encode(
            [query], prompt=QUERY_PROMPT, normalize_embeddings=True, show_progress_bar=False,
        )[0]
        if eligible is not None:
            if len(eligible) >= BROAD_FILTER_SIZE:
                return self._rank_broad_filter(embedding, top_k, eligible)
            # Bound the expression size for sparse filters.
            ids = sorted(eligible)
            hits = {}
            for start in range(0, len(ids), 1000):
                batch = ids[start:start + 1000]
                predicate = "product_id IN (" + ",".join(str(int(value)) for value in batch) + ")"
                hits.update(self._rank(embedding, top_k, predicate))
            return dict(sorted(hits.items(), key=lambda pair: (pair[1]["_distance"], pair[0]))[:top_k])
        return self._rank(embedding, top_k, f"platform = '{platform}'" if platform else None)

    def _rank_broad_filter(self, embedding, top_k, eligible):
        """Score every eligible vector exactly in one pass over an in-memory Lance projection."""
        import numpy as np

        if self._filtered_vectors is None:
            started = perf_counter()
            matrix = self.table.search().select(["chunk_id", "product_id", "vector"]).limit(
                self.manifest["vector_count"]
            ).to_arrow()
            if matrix.num_rows != self.manifest["vector_count"]:
                raise ValueError("Vector projection count differs from the manifest.")
            products = matrix["product_id"].combine_chunks().to_numpy()
            chunks = matrix["chunk_id"].to_pylist()
            values = matrix["vector"].combine_chunks().values.to_numpy().reshape(-1, DIMENSIONS)
            magnitudes = np.sqrt(np.einsum("ij,ij->i", values, values))
            if not np.isfinite(magnitudes).all() or np.any(magnitudes == 0):
                raise ValueError("Vector projection contains invalid norms.")
            self._filtered_vectors = products, chunks, values, magnitudes
            self.initialization_ms["broad_filter_projection"] = (perf_counter() - started) * 1000
        products, chunks, values, magnitudes = self._filtered_vectors
        positions = np.flatnonzero(np.isin(products, np.fromiter(eligible, dtype=products.dtype)))
        similarities = np.einsum("ij,j->i", values, embedding) / (magnitudes * np.linalg.norm(embedding))
        # Order by exact cosine similarity. Break ties by product, then chunk row.
        order = positions[np.lexsort((positions, products[positions], -similarities[positions]))]
        winners = {}
        for position in order:
            product_id = int(products[position])
            winners.setdefault(product_id, (chunks[position], float(1 - similarities[position])))
            if len(winners) == top_k:
                break
        if not winners:
            return {}
        selected = [chunk_id for chunk_id, _ in winners.values()]
        if any(not re.fullmatch(r"\d+:\d+", chunk_id) for chunk_id in selected):
            raise ValueError("Vector projection contains an invalid chunk ID.")
        predicate = "chunk_id IN (" + ",".join(f"'{chunk_id}'" for chunk_id in selected) + ")"
        hits = self.table.search().where(predicate).select([
            "chunk_id", "product_id", "platform", "source_id", "source_records", "text",
        ]).limit(len(selected)).to_list()
        by_chunk = {hit["chunk_id"]: hit for hit in hits}
        if set(by_chunk) != set(selected):
            raise ValueError("Vector projection facts could not be recovered from LanceDB.")
        return {product_id: {**by_chunk[chunk_id], "_distance": distance}
                for product_id, (chunk_id, distance) in winners.items()}

    def _rank(self, embedding, top_k, predicate):
        candidate_count = min(self.manifest["vector_count"], top_k * 3)
        winners = {}
        while True:
            search = self.table.search(embedding).distance_type("cosine").bypass_vector_index().select([
                "chunk_id", "product_id", "platform", "source_id", "source_records", "text", "_distance",
            ])
            if predicate:
                search = search.where(predicate, prefilter=True)
            hits = search.limit(candidate_count).to_list()
            winners.clear()
            for hit in sorted(hits, key=lambda item: (item["_distance"], item["chunk_id"])):
                winners.setdefault(hit["product_id"], hit)
                if len(winners) == top_k:
                    break
            if len(winners) == top_k or len(hits) < candidate_count or candidate_count >= self.manifest["vector_count"]:
                break
            candidate_count = min(candidate_count * 2, self.manifest["vector_count"])
        return winners

    def hydrate(self, winners):
        if not winners:
            return []
        with closing(open_catalog(self.catalog)) as connection:
            placeholders = ",".join("?" for _ in winners)
            facts = {
                row["id"]: dict(row) for row in connection.execute(
                    f"SELECT * FROM products WHERE id IN ({placeholders})", tuple(winners)
                )
            }
            sources = {}
            for row in connection.execute(
                f"""SELECT product_id, record_number, source_record_id,
                           json_extract(normalized_json, '$.product_url') AS product_url,
                           json_extract(normalized_json, '$.observed_at') AS observed_at
                    FROM source_records WHERE status = 'accepted'
                    AND product_id IN ({placeholders}) ORDER BY record_number""", tuple(winners)
            ):
                evidence = dict(row)
                sources.setdefault(evidence.pop("product_id"), []).append(evidence)
        self._check_catalog_version()
        results = []
        for product_id, hit in winners.items():
            product = facts.get(product_id)
            source_records = sources.get(product_id, [])
            if (product is None or any(product[field] != hit[field] for field in ("platform", "source_id"))
                    or [row["record_number"] for row in source_records] != hit["source_records"]):
                raise ValueError("Vector hit and SQLite facts disagree; rebuild the index")
            results.append({
                "similarity": 1.0 - hit["_distance"], "chunk_id": hit["chunk_id"],
                "matched_text": hit["text"], "product": product,
                "source": {"file": f"{hit['platform']}.csv", "records": source_records},
            })
        return results
