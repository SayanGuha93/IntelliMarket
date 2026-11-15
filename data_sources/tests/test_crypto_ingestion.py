import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from data_sources.crypto_api import CryptoAPIRateLimitError
from data_sources.crypto_ingestion import (
    CryptoRecordValidationError,
    normalize_record,
    run_ingestion,
    save_observation,
)
from database.migrate_crypto import MIGRATION_PATH, migrate


def sample_record(symbol="BTC", exchange="binance", timestamp="2026-11-15 05:57:17", **overrides):
    record = {
        "symbol": symbol,
        "source_exchange": exchange,
        "last": "64813.51",
        "last_btc": "1",
        "lowest": "62124.63",
        "highest": "64957.5",
        "daily_change_percentage": "0.071502241875525",
        "date": timestamp,
    }
    record.update(overrides)
    return record


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get_data(self, symbol):
        self.calls.append(symbol)
        value = self.responses[symbol]
        if isinstance(value, Exception):
            raise value
        return value


class CryptoIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "crypto_test.sqlite3"
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def connect(self):
        return sqlite3.connect(self.db_path)

    def test_normalizes_numeric_strings_and_preserves_provider_timestamp(self):
        record = normalize_record(sample_record(), "btc")
        self.assertEqual(record["symbol"], "BTC")
        self.assertEqual(record["last"], 64813.51)
        self.assertEqual(record["daily_change_percentage"], 0.071502241875525)
        self.assertEqual(record["provider_date"], "2026-11-15 05:57:17")
        self.assertEqual(json.loads(record["raw_payload_json"])["last"], "64813.51")

    def test_missing_optional_fields_are_null_but_required_fields_fail(self):
        sparse = {"symbol": "BTC", "source_exchange": "binance", "last": "1", "date": "raw timestamp"}
        normalized = normalize_record(sparse, "BTC")
        self.assertIsNone(normalized["last_btc"])
        self.assertIsNone(normalized["lowest"])
        with self.assertRaises(CryptoRecordValidationError):
            normalize_record({"symbol": "BTC", "source_exchange": "binance", "date": "t"}, "BTC")
        with self.assertRaises(CryptoRecordValidationError):
            normalize_record({**sparse, "source_exchange": ""}, "BTC")

    def test_rejects_invalid_nonfinite_negative_and_wrong_symbol_values(self):
        for invalid in ("not-a-number", "NaN", "Infinity", "-1"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(CryptoRecordValidationError):
                    normalize_record(sample_record(last=invalid), "BTC")
        with self.assertRaises(CryptoRecordValidationError):
            normalize_record(sample_record(symbol="ETH"), "BTC")

    def test_database_persistence_duplicate_prevention_and_exchange_separation(self):
        first = normalize_record(sample_record(), "BTC")
        other_exchange = normalize_record(sample_record(exchange="coinbase"), "BTC")
        with closing(self.connect()) as connection:
            self.assertTrue(save_observation(connection, first))
            connection.commit()
            self.assertFalse(save_observation(connection, first, collected_at_utc="2026-11-15T06:15:00Z"))
            connection.commit()
            self.assertTrue(save_observation(connection, other_exchange, collected_at_utc="2026-11-15T06:15:00Z"))
            connection.commit()

        with closing(self.connect()) as connection:
            assets = connection.execute("SELECT symbol, name FROM crypto_assets").fetchall()
            rows = connection.execute(
                "SELECT source_exchange, last, provider_date, collected_at_utc, raw_payload_json FROM crypto_market_history ORDER BY id"
            ).fetchall()
        self.assertEqual(assets, [("BTC", None)])
        self.assertEqual(len(rows), 2)
        self.assertEqual({row[0] for row in rows}, {"binance", "coinbase"})
        self.assertEqual(rows[0][2], "2026-11-15 05:57:17")
        self.assertTrue(rows[0][3].endswith("Z"))
        parsed_collected = datetime.fromisoformat(rows[0][3].replace("Z", "+00:00"))
        self.assertEqual(parsed_collected.utcoffset(), timedelta(0))
        self.assertEqual(json.loads(rows[0][4])["symbol"], "BTC")

    def test_ingestion_continues_after_individual_failure_and_reports_counts(self):
        client = FakeClient({
            "BTC": [sample_record()],
            "ETH": RuntimeError("temporary fake failure"),
            "SOL": [sample_record("SOL")],
        })
        timestamps = iter(("2026-11-15T06:00:00Z", "2026-11-15T06:00:00Z"))
        stats = run_ingestion(
            symbols=("BTC", "ETH", "SOL"), client=client,
            connection_factory=self.connect,
            collected_at_factory=lambda: next(timestamps), use_lock=False,
        )
        self.assertEqual(client.calls, ["BTC", "ETH", "SOL"])
        self.assertEqual(stats["fetched"], 2)
        self.assertEqual(stats["inserted"], 2)
        self.assertEqual(stats["skipped"], 0)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["assets_inserted"], 2)

    def test_persistent_rate_limit_stops_without_calling_remaining_symbols(self):
        client = FakeClient({"BTC": CryptoAPIRateLimitError("limited"), "ETH": [sample_record("ETH")]})
        stats = run_ingestion(
            symbols=("BTC", "ETH"), client=client,
            connection_factory=self.connect, use_lock=False,
        )
        self.assertEqual(client.calls, ["BTC"])
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["not_attempted"], 1)

    def test_watchlist_is_configurable_and_deduplicated(self):
        stats = run_ingestion(
            symbols="btc, ETH, BTC", client=FakeClient({"BTC": [sample_record()], "ETH": [sample_record("ETH")]}),
            connection_factory=self.connect, use_lock=False,
        )
        self.assertEqual(stats["symbols_requested"], 2)

    def test_additive_migration_creates_verified_backup_and_preserves_old_rows(self):
        with closing(self.connect()) as connection:
            connection.execute("CREATE TABLE products (product_id TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO products VALUES ('existing-product')")
            connection.commit()
        result = migrate(self.db_path)
        self.assertTrue(result["backup_verified"])
        self.assertTrue(result["backup_path"].is_file())
        with closing(sqlite3.connect(result["backup_path"])) as backup:
            self.assertEqual(backup.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1)
        with closing(self.connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name='crypto_assets'").fetchone())


if __name__ == "__main__":
    unittest.main()
