import sqlite3
from datetime import datetime

# Connect database
conn = sqlite3.connect("prices.db")

cursor = conn.cursor()

# =========================================
# CREATE PRICES TABLE
# =========================================

def create_table():

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT,
        price REAL,
        timestamp TEXT,
        source TEXT
    )
    """)

    conn.commit()

# =========================================
# INSERT PRICE DATA
# =========================================

def insert_price(product_name, price, source):

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO prices
    (product_name, price, timestamp, source)
    VALUES (?, ?, ?, ?)
    """, (product_name, price, timestamp, source))

    conn.commit()

# =========================================
# CLOSE CONNECTION
# =========================================

def close_connection():
    conn.close()