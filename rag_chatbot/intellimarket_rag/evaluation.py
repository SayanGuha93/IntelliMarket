"""Evaluate exact search against reviewed, non-exhaustive source-record labels."""

import json
import math
from contextlib import closing
from statistics import mean
from time import perf_counter

from .semantic import open_catalog


def evaluate_semantic(root, service):
    label_path = root / "evaluation" / "semantic_queries.jsonl"
    cases = [json.loads(line) for line in label_path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    reviews = []
    with closing(open_catalog(service.catalog)) as connection:
        for case in cases:
            expected = set(case["relevant"])
            if not expected:
                raise ValueError("Each evaluation query needs at least one reviewed item")
            for label in expected:
                platform, product_id = label.split(":", 1)
                if (case.get("platform", platform) != platform or connection.execute(
                        "SELECT 1 FROM products WHERE platform = ? AND source_id = ?",
                        (platform, product_id),
                    ).fetchone() is None):
                    raise ValueError(f"Invalid source label: {label}")

    service.search(cases[0]["query"], platform=cases[0].get("platform"), top_k=10)
    for case in cases:
        start = perf_counter()
        results = service.search(case["query"], platform=case.get("platform"), top_k=10)
        duration = (perf_counter() - start) * 1000
        retrieved = [
            {"id": f"{row['product']['platform']}:{row['product']['source_id']}",
             "name": row["product"]["name"], "similarity": row["similarity"]}
            for row in results
        ]
        expected = set(case["relevant"])
        positions = [position for position, row in enumerate(retrieved, 1) if row["id"] in expected]
        reviews.append({
            **case, "retrieved": retrieved, "latency_ms": duration,
            "recall_at_10": len(positions) / len(expected),
            "reciprocal_rank_at_10": 1 / positions[0] if positions else 0,
        })
    latencies = sorted(row["latency_ms"] for row in reviews)
    report = {
        "index_id": service.manifest["build_id"],
        "query_count": len(reviews),
        "reviewed_reference_count": sum(len(set(case["relevant"])) for case in cases),
        "recall_at_10": mean(row["recall_at_10"] for row in reviews),
        "mrr_at_10": mean(row["reciprocal_rank_at_10"] for row in reviews),
        "queries_with_reviewed_hit": sum(row["reciprocal_rank_at_10"] > 0 for row in reviews),
        "mean_latency_ms": mean(latencies),
        "p95_latency_ms": latencies[math.ceil(len(latencies) * 0.95) - 1],
        "label_scope": "Selected reviewed positive examples. Unjudged products may also be relevant.",
        "latency_scope": "Warm process, query encoding through SQLite fact and source hydration.",
        "queries": reviews,
    }
    output = root / "artifacts" / "semantic_evaluation.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {name: value for name, value in report.items() if name != "queries"}
