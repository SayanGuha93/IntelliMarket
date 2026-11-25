"""Run the standalone IntelliMarket catalog and chatbot."""

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

from .catalog import SORTS, build, search
from .paths import catalog_path, project_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="Validate and ingest the two original CSVs")
    query = commands.add_parser("search", help="Search the catalog and print JSON")
    for field in ("keywords", "name", "brand", "category", "colour", "product-id",
                  "min-price", "max-price", "min-rating", "max-rating"):
        query.add_argument(f"--{field}")
    query.add_argument("--platform", choices=("flipkart", "myntra"))
    query.add_argument("--price-field", choices=("recorded", "retail"), default="recorded")
    query.add_argument("--sort", choices=(*SORTS, "relevance"), default="name")
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--offset", type=int, default=0)
    index = commands.add_parser("index", help="Build or reuse the exact semantic index")
    index.add_argument("--batch-size", type=int, default=48)
    semantic = commands.add_parser("semantic", help="Search the semantic index and return SQLite facts")
    semantic.add_argument("query")
    semantic.add_argument("--top-k", type=int, default=10)
    semantic.add_argument("--platform", choices=("flipkart", "myntra"))
    evaluate = commands.add_parser("evaluate-semantic", help="Score the reviewed semantic query set")
    for command_parser in (index, semantic, evaluate):
        command_parser.add_argument("--device", default="auto")
        command_parser.add_argument("--threads", type=int, default=6)
    hybrid = commands.add_parser("hybrid", help="Search with exact filters, BM25 and semantic fusion")
    hybrid.add_argument("query")
    hybrid.add_argument("--mode", choices=("fts", "semantic", "hybrid", "rerank"), default="hybrid")
    hybrid.add_argument("--top-k", type=int, default=10)
    hybrid.add_argument("--keyword-pool", type=int, default=100)
    hybrid.add_argument("--semantic-pool", type=int, default=100)
    hybrid.add_argument("--rrf-k", type=int, default=30)
    hybrid.add_argument("--keyword-weight", type=float, default=1.0)
    hybrid.add_argument("--semantic-weight", type=float, default=1.0)
    hybrid.add_argument("--rerank-pool", type=int, default=40)
    compare = commands.add_parser("compare", help="Find cross-platform candidates for a source product")
    compare.add_argument("platform", choices=("flipkart", "myntra"))
    compare.add_argument("product_id")
    compare.add_argument("--top-k", type=int, default=5)
    benchmark = commands.add_parser("evaluate-hybrid", help="Benchmark retrieval and matching")
    for command_parser in (hybrid, compare, benchmark):
        command_parser.add_argument("--device", default="cpu")
        command_parser.add_argument("--threads", type=int, default=6)
    chat = commands.add_parser("chat", help="Start an independent grounded catalog chatbot")
    chat_eval = commands.add_parser("evaluate-chat", help="Run chatbot dialogs and adaptive retrieval evaluation")
    for command_parser in (chat, chat_eval):
        command_parser.add_argument("--provider", choices=("fallback", "gemini", "ollama"))
        command_parser.add_argument("--model")
        command_parser.add_argument("--device", default="cpu")
        command_parser.add_argument("--threads", type=int, default=6)
        command_parser.add_argument("--mode", choices=("adaptive", "fts", "semantic", "hybrid", "rerank"),
                                    default="adaptive")
        command_parser.add_argument("--keyword-limit", type=int, default=4)
        command_parser.add_argument("--rerank", action="store_true")
        command_parser.add_argument("--top-k", type=int, default=5)
        command_parser.add_argument("--llm-intent", action="store_true",
                                    help="Enable optional LLM intent refinement before retrieval")
    chat.add_argument("--debug", action="store_true")
    for subparser in (build_parser, query, index, semantic, evaluate, hybrid, compare, benchmark, chat, chat_eval):
        subparser.add_argument("--root", type=Path, help="Override the chatbot project directory")
    for subparser in (query, index, semantic, evaluate, hybrid, compare, benchmark, chat, chat_eval):
        subparser.add_argument("--catalog", type=Path, help="Override the SQLite catalog file")
    for subparser in (index, semantic, evaluate, hybrid, compare, benchmark, chat, chat_eval):
        subparser.add_argument("--index-dir", type=Path, help="Override the directory containing active.json")
    options = vars(parser.parse_args())
    command = options.pop("command")
    root = project_root(options.pop("root"))
    asset_options = {name: options.pop(name) for name in ("catalog", "index_dir") if name in options}
    try:
        if command == "build":
            result = build(root)
        elif command == "search":
            result = search(catalog_path(root, **asset_options), **options)
        elif command == "chat":
            from .chat_cli import interactive

            interactive(root, **asset_options, **options)
            return
        elif command == "evaluate-chat":
            from .chat_cli import configured_bot
            from .chat_evaluation import evaluate_chat

            result = evaluate_chat(root, configured_bot(root, **asset_options, **options))
        elif command in {"hybrid", "compare", "evaluate-hybrid"}:
            from .hybrid import HybridSearch, RetrievalConfig
            from .query import Query, parse_query

            service = HybridSearch(root, device=options.pop("device"), threads=options.pop("threads"),
                                   **asset_options)
            if command == "hybrid":
                intent = parse_query(options.pop("query"))
                top_k, mode = options.pop("top_k"), options.pop("mode")
                if intent.comparison:
                    from .matching import compare as compare_products

                    result = compare_products(service, intent, top_k=top_k)
                else:
                    result = service.search(intent, top_k=top_k, mode=mode, config=RetrievalConfig(**options))
            elif command == "compare":
                from .matching import compare as compare_products

                top_k = options.pop("top_k")
                result = compare_products(service, Query(comparison=True, **options), top_k=top_k)
            else:
                from .benchmark import benchmark_hybrid

                result = benchmark_hybrid(root, service)
        else:
            from .semantic import PRICE_NOTICE, SemanticSearch, build_index

            if command == "index":
                def progress(done, total, chunks, elapsed):
                    print(f"{done:,}/{total:,} products | {chunks:,} chunks | {elapsed:.1f}s",
                          file=sys.stderr, flush=True)

                result = build_index(root, progress=progress, **asset_options, **options)
            else:
                service = SemanticSearch(root, device=options.pop("device"), threads=options.pop("threads"),
                                         **asset_options)
                if command == "semantic":
                    result = {"price_notice": PRICE_NOTICE, "results": service.search(**options)}
                else:
                    from .evaluation import evaluate_semantic

                    result = evaluate_semantic(root, service)
    except (OSError, ValueError, sqlite3.Error, csv.Error, RuntimeError, ImportError) as error:
        parser.exit(1, f"Catalog error: {error}\n")
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
