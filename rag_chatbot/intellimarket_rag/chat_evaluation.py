"""Run real catalog dialogues and compare the fixed router against retrieval baselines."""

import json
import math
from collections import Counter
from contextlib import closing
from statistics import mean
from time import perf_counter

from .benchmark import ranking_metrics, read_cases
from .evidence import citation, format_fact
from .hybrid import sql_constraints
from .intent import Intent, query_payload
from .query import parse_query
from .semantic import PRICE_NOTICE, open_catalog


def latency(values):
    values = sorted(values)
    return {"mean_ms": mean(values), "p95_ms": values[math.ceil(.95 * len(values)) - 1],
            "measured": len(values)} if values else None


def check_turn(connection, turn, expected, previous, prior_focus):
    items = turn.evidence
    present = {item["evidence_id"] for item in items}
    checks = {"intent": turn.action == expected["action"]}
    if "empty" in expected:
        checks["empty"] = not items and turn.answer.startswith("No catalog")
    if "relevant" in expected:
        checks["relevance"] = expected["relevant"] in present
    if "comparison" in expected:
        checks["comparison"] = turn.comparison == expected["comparison"]
    if "positions" in expected:
        checks["follow_up"] = [item["id"] for item in items] == [
            previous[position - 1] for position in expected["positions"]
        ]
    elif turn.action == "detail" and prior_focus:
        checks["follow_up"] = [item["id"] for item in items] == [prior_focus]
    if "contains" in expected:
        checks["answer"] = expected["contains"].casefold() in turn.answer.casefold()
    if "filters" in expected:
        checks["follow_up_filters"] = bool(turn.query) and all(
            query_payload(turn.query).get(key) == value for key, value in expected["filters"].items()
        )
    if turn.query and turn.action in {"search", "cheaper"}:
        where, params, _ = sql_constraints(turn.query)
        checks["constraints"] = all(connection.execute(
            f"SELECT 1 FROM products p WHERE p.id=? AND ({where})", (item["id"], *params),
        ).fetchone() for item in items)
    if items:
        checks.update(citations=True, prices=True, ratings=True, groundedness=True)
    for item in items:
        product = connection.execute("SELECT * FROM products WHERE id=?", (item["id"],)).fetchone()
        known = [row[0] for row in connection.execute(
            "SELECT record_number FROM source_records WHERE status='accepted' AND product_id=? ORDER BY record_number",
            (item["id"],),
        )]
        checks["citations"] &= (known == [row["record_number"] for row in item["records"]]
                                and citation(item) in turn.answer)
        for field, value in ((product["price_field"], product["price_minor"]),
                             ("retail_price", product["retail_price_minor"])):
            checks["prices"] &= item["facts"].get(field) == value and (
                value is None or format_fact(field, value) in turn.answer
            )
        checks["prices"] &= PRICE_NOTICE in turn.answer
        for field in ("rating", "rating_count"):
            checks["ratings"] &= item["facts"].get(field) == product[field] and (
                product[field] is None or format_fact(field, product[field]) in turn.answer
            )
        checks["groundedness"] &= item["name"] == product["name"] and all(
            json.loads(product["attributes"]).get(field.removeprefix("attribute:")) == value
            for field, value in item["facts"].items() if field.startswith("attribute:")
        )
    return checks


def router_benchmark(root, bot):
    directory = root / "evaluation"
    cohorts = {
        "original": [{**case, "input": case["query"] + (
            f"; platform:{case['platform']}" if "platform" in case else ""
        )} for case in read_cases(directory / "semantic_queries.jsonl")],
        "held_out": [{**case, "input": case["query"]} for case in read_cases(directory / "hybrid_queries.jsonl")
                     if case["split"] == "held-out" and case.get("relevant")],
    }
    report = {}
    for cohort, cases in cohorts.items():
        report[cohort] = {}
        for method in ("adaptive", "fts", "semantic", "hybrid", "rerank"):
            metrics, times, routes = [], [], Counter()
            for case in cases:
                query = parse_query(case["input"])
                route = bot.router.choose(Intent("search", query))[0] if method == "adaptive" else method
                started = perf_counter()
                result = bot.retrieval.search(query, mode="fts" if route == "sql" else route, top_k=10)
                times.append((perf_counter() - started) * 1000)
                routes[route] += 1
                metrics.append(ranking_metrics(set(case["relevant"]), [
                    f"{row['product']['platform']}:{row['product']['source_id']}" for row in result
                ]))
            report[cohort][method] = {"queries": len(cases), "routes": dict(routes),
                                     **{key: mean(row[key] for row in metrics) for key in metrics[0]},
                                     **latency(times)}
    return report


def evaluate_chat(root, bot):
    cases = read_cases(root / "evaluation" / "chat_cases.jsonl")
    dialogs = []
    counts = Counter()
    successes = Counter()
    turns = []
    # Warm local retrieval only. Execution timings exclude the first model import.
    bot.retrieval.search(parse_query("cotton clothing"), top_k=2)
    with closing(open_catalog(bot.retrieval.catalog)) as connection:
        for case in cases:
            session = bot.new_session()
            transcript = []
            for expected in case["turns"]:
                previous, focus = session.order, session.focus
                turn = bot.respond(session, expected["text"])
                checks = check_turn(connection, turn, expected, previous, focus)
                counts.update(checks.keys())
                successes.update(key for key, passed in checks.items() if passed)
                turns.append(turn)
                transcript.append({
                    "user": expected["text"], "assistant": turn.answer, "action": turn.action,
                    "strategy": turn.strategy, "reason": turn.reason, "checks": checks,
                    "evidence_ids": [item["evidence_id"] for item in turn.evidence],
                    "retrieval_ms": turn.retrieval_ms, "intent_ms": turn.intent_ms,
                    "generation_ms": turn.generation_ms, "total_ms": turn.total_ms,
                    "provider_status": turn.provider_status, "provider_calls": turn.provider_calls,
                    "input_tokens": turn.input_tokens, "output_tokens": turn.output_tokens,
                    "diagnostics": turn.diagnostics(),
                })
            dialogs.append({"id": case["id"], "turns": transcript})
    report = {
        "provider": bot.configured_provider,
        "requested_provider": bot.requested_provider,
        "startup_fallback_reason": bot.initialization_failure,
        "cases": len(cases), "multi_turn_cases": sum(len(case["turns"]) > 1 for case in cases),
        "turns": len(turns),
        "cases_passed": sum(all(all(turn["checks"].values()) for turn in case["turns"]) for case in dialogs),
        "checks": {name: {"passed": successes[name], "tested": total} for name, total in counts.items()},
        "retrieval": latency([turn.retrieval_ms for turn in turns if turn.retrieval_ms > 0]),
        "llm_intent": latency([turn.intent_ms for turn in turns if turn.intent_ms > 0]),
        "llm_generation": latency([turn.generation_ms for turn in turns if turn.generation_ms > 0]),
        "end_to_end": latency([turn.total_ms for turn in turns]),
        "tokens": {
            key: sum(values) if (values := [getattr(turn, key) for turn in turns
                                           if getattr(turn, key) is not None]) else None
            for key in ("input_tokens", "output_tokens")
        },
        "provider_outcomes": dict(Counter(turn.provider_status for turn in turns)),
        "actual_answer_providers": dict(Counter(turn.diagnostics()["actual_provider"] for turn in turns)),
        "gemini_turns_with_successful_inference": sum(
            turn.diagnostics()["gemini_inference_succeeded"] is True for turn in turns
        ),
        "fallback_turns": sum(turn.diagnostics()["fallback_triggered"] for turn in turns),
        "adaptive_benchmark": router_benchmark(root, bot),
    }
    directory = root / "artifacts"
    (directory / "chat_evaluation.json").write_text(json.dumps(
        {**report, "dialogs": dialogs}, indent=2, ensure_ascii=False
    ) + "\n", encoding="utf-8")
    sample = {"pocket-follow", "second-follow", "compare-positions", "cheaper-follow",
              "platform-follow", "cross-denim", "reset-follow"}
    (directory / "chat_transcripts.txt").write_text("\n\n".join(
        case["id"] + "\n" + "\n".join(
            f"You> {turn['user']}\nAssistant> {turn['assistant']}" for turn in case["turns"]
        ) for case in dialogs if case["id"] in sample
    ) + "\n", encoding="utf-8")
    return report
