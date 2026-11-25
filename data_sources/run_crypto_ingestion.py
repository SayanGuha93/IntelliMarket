"""Manual/scheduler-friendly runner for the independent crypto ingestion."""

import argparse
import logging

from data_sources.crypto_ingestion import DEFAULT_WATCHLIST, run_ingestion


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ingest live crypto market snapshots.")
    parser.add_argument(
        "--symbols",
        help="Comma-separated watchlist; defaults to CRYPTO_WATCHLIST or the configured ten symbols.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    symbols = args.symbols if args.symbols is not None else DEFAULT_WATCHLIST
    stats = run_ingestion(symbols=symbols)
    print(
        "Crypto ingestion: "
        f"fetched={stats['fetched']} inserted={stats['inserted']} "
        f"skipped={stats['skipped']} failed={stats['failed']} "
        f"assets_inserted={stats['assets_inserted']} "
        f"assets_updated={stats['assets_updated']} "
        f"not_attempted={stats['not_attempted']}"
    )
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
