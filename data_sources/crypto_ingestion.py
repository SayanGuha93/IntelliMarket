"""Independent FreeCryptoAPI ingestion into crypto-only SQLite tables."""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from database.connection import get_connection
from data_sources.crypto_api import (
    CryptoAPIRateLimitError,
    FreeCryptoAPIClient,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_WATCHLIST = (
    "BTC", "ETH", "USDT", "BNB", "SOL", "XRP", "USDC", "TRX", "DOGE", "ADA"
)
NUMERIC_FIELDS = ("last", "last_btc", "lowest", "highest", "daily_change_percentage")
REQUIRED_STRING_FIELDS = ("symbol", "source_exchange", "date")


class CryptoRecordValidationError(ValueError):
    pass


def configured_watchlist(value=None):
    """Read a configurable comma-separated watchlist or use the fixed default."""
    raw = value if value is not None else os.getenv("CRYPTO_WATCHLIST")
    if raw is None or not str(raw).strip():
        return DEFAULT_WATCHLIST
    entries = raw.split(",") if isinstance(raw, str) else raw
    symbols = []
    for item in entries:
        symbol = item.strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    if not symbols:
        raise ValueError("The configured crypto watchlist is empty.")
    return tuple(symbols)


def _numeric_value(record, field, *, required=False):
    value = record.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise CryptoRecordValidationError(f"Required numeric field '{field}' is missing.")
        return None
    if isinstance(value, bool):
        raise CryptoRecordValidationError(f"Numeric field '{field}' is invalid.")
    try:
        decimal_value = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise CryptoRecordValidationError(f"Numeric field '{field}' is invalid.") from None
    if not decimal_value.is_finite():
        raise CryptoRecordValidationError(f"Numeric field '{field}' must be finite.")
    if field in {"last", "last_btc", "lowest", "highest"} and decimal_value < 0:
        raise CryptoRecordValidationError(f"Numeric field '{field}' cannot be negative.")
    number = float(decimal_value)
    if not math.isfinite(number):
        raise CryptoRecordValidationError(f"Numeric field '{field}' is outside SQLite REAL range.")
    return number


def normalize_record(record, requested_symbol):
    if not isinstance(record, dict):
        raise CryptoRecordValidationError("Market record must be an object.")
    normalized_symbol = str(record.get("symbol", "")).strip().upper()
    if not normalized_symbol or normalized_symbol != requested_symbol.upper():
        raise CryptoRecordValidationError("Response symbol does not match the requested symbol.")
    source_exchange = record.get("source_exchange")
    if not isinstance(source_exchange, str) or not source_exchange.strip():
        raise CryptoRecordValidationError("Required field 'source_exchange' is missing.")
    provider_date = record.get("date")
    if not isinstance(provider_date, str) or not provider_date:
        raise CryptoRecordValidationError("Required provider field 'date' is missing.")
    normalized = {
        "symbol": normalized_symbol,
        "source_exchange": source_exchange.strip(),
        "last": _numeric_value(record, "last", required=True),
        "last_btc": _numeric_value(record, "last_btc"),
        "lowest": _numeric_value(record, "lowest"),
        "highest": _numeric_value(record, "highest"),
        "daily_change_percentage": _numeric_value(record, "daily_change_percentage"),
        # The provider's timestamp is retained verbatim; its timezone is unspecified.
        "provider_date": provider_date,
        "raw_payload_json": json.dumps(record, ensure_ascii=False, separators=(",", ":")),
    }
    return normalized


def _collected_at_utc():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def save_observation(connection, record, *, collected_at_utc=None):
    """Upsert an asset and insert a unique source timestamp observation."""
    collected_at_utc = collected_at_utc or _collected_at_utc()
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """INSERT INTO crypto_assets (symbol, name)
           VALUES (?, NULL)
           ON CONFLICT(symbol) DO UPDATE SET updated_at = CURRENT_TIMESTAMP""",
        (record["symbol"],),
    )
    asset_id = connection.execute(
        "SELECT id FROM crypto_assets WHERE symbol = ?", (record["symbol"],)
    ).fetchone()[0]
    cursor = connection.execute(
        """INSERT INTO crypto_market_history (
               asset_id, source_exchange, last, last_btc, lowest, highest,
               daily_change_percentage, provider_date, collected_at_utc,
               raw_payload_json
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(asset_id, source_exchange, provider_date) DO NOTHING""",
        (
            asset_id, record["source_exchange"], record["last"], record["last_btc"],
            record["lowest"], record["highest"], record["daily_change_percentage"],
            record["provider_date"], collected_at_utc, record["raw_payload_json"],
        ),
    )
    return cursor.rowcount == 1


@contextmanager
def _single_instance_lock():
    """Prevent overlapping scheduled runs using a temp-file OS lock."""
    lock_path = os.path.join(tempfile.gettempdir(), "intellimarket_crypto_ingestion.lock")
    stream = open(lock_path, "a+b")
    try:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0 and os.path.getsize(lock_path) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("A crypto ingestion run is already active.") from None
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("A crypto ingestion run is already active.") from None
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        stream.close()


def run_ingestion(*, symbols=None, client=None, connection_factory=None, collected_at_factory=None, use_lock=True):
    """Fetch each watchlist symbol separately and preserve successful records."""
    symbols = configured_watchlist(symbols)
    client = client or FreeCryptoAPIClient()
    connection_factory = connection_factory or get_connection
    collected_at_factory = collected_at_factory or _collected_at_utc
    stats = {
        "symbols_requested": len(symbols),
        "fetched": 0,
        "inserted": 0,
        "skipped": 0,
        "failed": 0,
        "assets_inserted": 0,
        "assets_updated": 0,
        "not_attempted": 0,
    }

    lock_context = _single_instance_lock() if use_lock else _null_context()
    with lock_context:
        connection = connection_factory()
        try:
            for position, symbol in enumerate(symbols):
                try:
                    before_asset = connection.execute(
                        "SELECT id FROM crypto_assets WHERE symbol = ?", (symbol,)
                    ).fetchone()
                    records = client.get_data(symbol)
                    valid_records = [normalize_record(record, symbol) for record in records]
                    if not valid_records:
                        raise CryptoRecordValidationError("No market records were returned.")

                    stats["fetched"] += len(valid_records)
                    local_inserted = 0
                    local_skipped = 0
                    for record in valid_records:
                        inserted = save_observation(
                            connection, record,
                            collected_at_utc=collected_at_factory(),
                        )
                        if inserted:
                            local_inserted += 1
                        else:
                            local_skipped += 1
                    connection.commit()
                    stats["inserted"] += local_inserted
                    stats["skipped"] += local_skipped
                    if before_asset is None:
                        stats["assets_inserted"] += 1
                    else:
                        stats["assets_updated"] += 1
                except CryptoAPIRateLimitError as exc:
                    connection.rollback()
                    stats["failed"] += 1
                    stats["not_attempted"] = len(symbols) - position - 1
                    LOGGER.error("Crypto ingestion stopped at %s: %s", symbol, exc)
                    break
                except Exception as exc:
                    connection.rollback()
                    stats["failed"] += 1
                    LOGGER.error("Crypto ingestion failed for %s: %s", symbol, exc)
                    continue
        finally:
            connection.close()

    LOGGER.info(
        "Crypto ingestion complete: symbols=%d fetched=%d inserted=%d skipped=%d failed=%d assets_inserted=%d assets_updated=%d not_attempted=%d",
        stats["symbols_requested"], stats["fetched"], stats["inserted"],
        stats["skipped"], stats["failed"], stats["assets_inserted"],
        stats["assets_updated"], stats["not_attempted"],
    )
    return stats


@contextmanager
def _null_context():
    yield
