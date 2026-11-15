"""Back up prices.db, then apply the additive Google Books catalog schema."""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from database.connection import DATABASE_PATH


MIGRATION_PATH = Path(__file__).resolve().parent / "migrations" / "001_google_books_catalog.sql"


def migrate(database_path=DATABASE_PATH):
    database_path = Path(database_path).resolve()
    if not database_path.exists():
        raise FileNotFoundError(f"Database does not exist: {database_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = database_path.with_name(
        f"{database_path.stem}.before_google_books_{timestamp}{database_path.suffix}"
    )
    shutil.copy2(database_path, backup_path)

    try:
        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    except Exception:
        # The original database is retained; restore the pre-migration copy.
        shutil.copy2(backup_path, database_path)
        raise

    return backup_path


if __name__ == "__main__":
    print(f"Migration complete. Backup: {migrate()}")
