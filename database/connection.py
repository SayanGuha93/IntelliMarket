import sqlite3
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent

_path = Path(os.getenv("INTELLIMARKET_DB_PATH", str(BASE_DIR / "prices.db")))
DATABASE_PATH = _path if _path.is_absolute() else BASE_DIR / _path


def get_connection():
    return sqlite3.connect(DATABASE_PATH)


def initialize_database():

    connection = get_connection()

    schema_path = Path(__file__).resolve().parent / "schema.sql"

    with open(schema_path, "r", encoding="utf-8") as file:
        schema = file.read()

    connection.executescript(schema)

    connection.commit()
    connection.close()


if __name__ == "__main__":
    initialize_database()
    print("Database initialized successfully.")
