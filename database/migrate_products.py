import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BASE_DIR / "prices.db"

connection = sqlite3.connect(DATABASE_PATH)
cursor = connection.cursor()

cursor.execute("ALTER TABLE products RENAME TO products_old")

cursor.execute("""
CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    brand TEXT,
    model TEXT,
    category TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
INSERT INTO products (
    product_id,
    product_name,
    brand,
    category,
    created_at
)
SELECT
    product_id,
    product_name,
    brand,
    category,
    created_at
FROM products_old
""")

cursor.execute("""
DROP TABLE products_old
""")

connection.commit()
connection.close()

print("Products table migrated successfully.")
