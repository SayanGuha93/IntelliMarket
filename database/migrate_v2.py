import sqlite3

DATABASE = "prices.db"


def migrate():
    connection = sqlite3.connect(DATABASE)
    cursor = connection.cursor()

    print("Continuing database migration...")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL,
            price REAL NOT NULL,
            mrp REAL,
            discount REAL,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (listing_id)
                REFERENCES product_listings(listing_id)
        )
    """)

    cursor.execute("""
        INSERT INTO price_history (
            listing_id,
            price,
            mrp,
            discount,
            recorded_at
        )
        SELECT
            pl.listing_id,
            old.price,
            old.mrp,
            old.discount,
            old.recorded_at
        FROM price_history_old old
        JOIN product_listings pl
            ON old.product_id = pl.product_id
    """)

    cursor.execute("""
        DROP TABLE price_history_old
    """)

    connection.commit()
    connection.close()

    print("Database migration completed successfully.")


if __name__ == "__main__":
    migrate()