"""Reproducible retrieval benchmark backed by source-checked labels and SQL oracles."""

import json
import math
from contextlib import closing
from statistics import mean
from time import perf_counter

from .matching import audit_identity, compare
from .query import QueryError, parse_query
from .semantic import open_catalog


MODES = ("fts", "semantic", "hybrid", "rerank")


def read_cases(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def label(product):
    return f"{product['platform']}:{product['source_id']}"


def ranking_metrics(expected, ranked):
    positions = [rank for rank, item in enumerate(ranked[:10], 1) if item in expected]
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(10, len(expected)) + 1))
    return {
        "recall_at_5": sum(rank <= 5 for rank in positions) / len(expected),
        "recall_at_10": len(positions) / len(expected),
        "mrr_at_10": 1 / positions[0] if positions else 0,
        "ndcg_at_10": sum(1 / math.log2(rank + 1) for rank in positions) / ideal,
    }


def summarize(rows):
    summary = {}
    for mode in MODES:
        entries = [row["runs"][mode] for row in rows if mode in row.get("runs", {})]
        latencies = sorted(entry["latency_ms"] for entry in entries)
        with_labels = [entry["metrics"] for entry in entries if "metrics" in entry]
        with_oracle = [entry["oracle_ok"] for entry in entries if "oracle_ok" in entry]
        structured = [entry["oracle_ok"] for entry in entries
                      if entry.get("deterministic") and "oracle_ok" in entry]
        summary[mode] = {
            "ranked_cases": len(with_labels),
            **{key: mean(metrics[key] for metrics in with_labels)
               for key in (with_labels[0] if with_labels else [])},
            "mean_ms": mean(latencies) if latencies else None,
            "p95_ms": latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None,
            "filter_correct": sum(with_oracle), "filter_cases": len(with_oracle),
            "deterministic_correct": sum(structured), "deterministic_cases": len(structured),
        }
    return summary


def benchmark_hybrid(root, service):
    path = root / "evaluation"
    legacy = [{**case, "split": "legacy", "input": case["query"] + (
        f"; platform:{case['platform']}" if "platform" in case else ""
    )} for case in read_cases(path / "semantic_queries.jsonl")]
    new = read_cases(path / "hybrid_queries.jsonl")
    review_path = path / "pooled_reviews.jsonl"
    reviews = {row["query"]: row["verified"] for row in read_cases(review_path)} if review_path.is_file() else {}
    results = []
    # Warm the model/store once so ranking latency measures requests rather than startup.
    service.search(parse_query("cotton clothing"), top_k=3)
    with closing(open_catalog(service.catalog)) as connection:
        known_labels = {label(row) for row in connection.execute("SELECT platform,source_id FROM products")}
        for case in legacy + new:
            text = case.get("input", case["query"])
            output = {"query": case["query"], "split": case["split"]}
            try:
                intent = parse_query(text)
            except QueryError as error:
                if not case.get("error"):
                    raise
                output["expected_rejection"] = str(error)
                results.append(output)
                continue
            if case.get("error"):
                raise RuntimeError(f"Ambiguous case was accepted: {text}")
            if intent.comparison:
                found = compare(service, intent, top_k=3)
                output["comparison"] = {"status": found["status"],
                    "candidates": [{"id": label(row["product"]), "evidence": row["evidence"]}
                                   for row in found["candidates"]]}
                results.append(output)
                continue
            expected = set(case.get("relevant", []))
            judgments = reviews.get(case["query"], [])
            pooled = {item["id"] for item in judgments if item["relevant"]}
            if not (expected | {item["id"] for item in judgments}) <= known_labels:
                raise ValueError(f"Unknown catalog labels for {text}")
            output["original_labels"], output["reviewed_additions"] = sorted(expected), sorted(pooled)
            output["runs"] = {}
            oracle = case.get("oracle")
            deterministic = not intent.terms or bool(intent.product_id)
            eligible = None
            if oracle is not None:
                # Oracle expressions are authored evaluation fixtures, never user input.
                order = case.get("order", "p.name_key,p.id")
                sql = f"SELECT p.id FROM products p WHERE ({oracle}) ORDER BY {order}"
                eligible = [row[0] for row in connection.execute(sql)]
            for mode in MODES:
                start = perf_counter()
                rows = service.search(intent, mode=mode, top_k=10)
                run = {"latency_ms": (perf_counter() - start) * 1000, "deterministic": deterministic,
                       "retrieved": [{"id": label(row["product"]), "name": row["product"]["name"]}
                                     for row in rows]}
                ids = [row["product"]["id"] for row in rows]
                if eligible is not None:
                    run["oracle_ok"] = ids == eligible[:10] if deterministic else (
                        bool(ids) and set(ids) <= set(eligible))
                    if not run["oracle_ok"]:
                        raise AssertionError(f"Filter/sort oracle failed for {mode}: {text}")
                if expected:
                    candidates = [row["id"] for row in run["retrieved"]]
                    run["original_metrics"] = ranking_metrics(expected, candidates)
                    run["metrics"] = ranking_metrics(expected | pooled, candidates)
                output["runs"][mode] = run
            observed_pool = {item["id"] for run in output["runs"].values() for item in run["retrieved"]}
            output["previous_judgments_in_current_pool"] = sorted(
                {item["id"] for item in judgments} & observed_pool
            )
            results.append(output)
    original = []
    for row in results:
        if row["split"] == "legacy":
            original.append({**row, "runs": {
                mode: {**run, "metrics": run["original_metrics"]} for mode, run in row["runs"].items()
            }})
    report = {
        "expanded_cases": len(results),
        "original": summarize(original),
        "expanded": summarize(results),
        "development": summarize([row for row in results if row["split"] == "development"]),
        "held_out": summarize([row for row in results if row["split"] == "held-out"]),
        "pooled_reviewed_cases": len(reviews),
        "pooled_judgments": sum(len(items) for items in reviews.values()),
        "verified_pool_labels": reviews,
        "identity_audit": audit_identity(service.catalog),
        "cases": results,
    }
    (root / "artifacts" / "hybrid_evaluation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {key: value for key, value in report.items() if key not in {"cases", "verified_pool_labels"}}
