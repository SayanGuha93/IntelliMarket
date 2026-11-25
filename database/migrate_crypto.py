"""Back up prices.db, then apply the additive cryptocurrency schema."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from database.connection import DATABASE_PATH

MIGRATION_PATH = Path(__file__).resolve().parent / "migrations" / "002_crypto_tables.sql"
CRYPTO_TABLES = {"crypto_assets", "crypto_market_history"}


def _table_counts(connection):
    names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        for name in names
    }


def migrate(database_path=DATABASE_PATH):
    database_path = Path(database_path).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {database_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = database_path.with_name(
        f"{database_path.stem}.before_crypto_{timestamp}{database_path.suffix}"
    )

    source = sqlite3.connect(database_path)
    backup = sqlite3.connect(backup_path)
    try:
        before_counts = _table_counts(source)
        source.backup(backup)
        backup_check = backup.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        backup.close()
        source.close()

    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise RuntimeError("Database backup was not created successfully.")
    if backup_check != "ok":
        raise RuntimeError(f"Database backup verification failed: {backup_check}")

    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("BEGIN IMMEDIATE;\n" + migration_sql + "\nCOMMIT;")
        after_counts = _table_counts(connection)
        for table, count in before_counts.items():
            if table not in CRYPTO_TABLES and after_counts.get(table) != count:
                raise RuntimeError(f"Existing table row count changed: {table}")
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()

    return {
        "database_path": database_path,
        "backup_path": backup_path,
        "backup_verified": True,
        "existing_table_counts": before_counts,
        "crypto_tables": sorted(CRYPTO_TABLES),
    }


if __name__ == "__main__":
    result = migrate()
    print(f"Crypto schema migration complete; backup verified: {result['backup_path']}")
