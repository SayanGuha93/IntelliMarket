
import sqlite3
from database.connection import get_connection
from data_sources.fake_store import (
    get_products as get_fake_store_products,
)
from data_sources.mock_api import (
    get_products as get_mock_products,
)

# Collect both sources: 20 Fake Store + 2 mock products.

def collect_price_history():
    """Store at most one price observation per listing per UTC day."""

    products = (
        get_fake_store_products()
        + get_mock_products()
    )

    connection = get_connection()
    cursor = connection.cursor()

    saved = 0
    skipped = 0
    missing = 0

    try:
        for product in products:
            # Find the existing listing; do not create new products.
            cursor.execute(
                """
                SELECT listing_id
                FROM product_listings
                WHERE source = ?
                  AND external_product_id = ?
                """,
                (
                    product["source"],
                    product["product_id"],
                ),
            )

            listing = cursor.fetchone()

            if listing is None:
                print(
                    f"Listing not found: "
                    f"{product['product_name']}"
                )
                missing += 1
                continue

            listing_id = listing[0]

            # Avoid duplicate collection records on the same UTC day.
            cursor.execute(
                """
                SELECT price
                FROM price_history
                WHERE listing_id = ?
                  AND date(recorded_at) = date('now')
                LIMIT 1
                """,
                (listing_id,),
            )

            existing_today = cursor.fetchone()

            if existing_today is not None:
                print(
                    f"Already collected today: "
                    f"{product['product_name']} "
                    f"(price: {existing_today[0]:.2f})"
                )
                skipped += 1
                continue

            # Save the actual price returned by the API.
            cursor.execute(
                """
                INSERT INTO price_history (
                    listing_id,
                    price,
                    mrp,
                    discount
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    listing_id,
                    product["price"],
                    product.get("mrp"),
                    product.get("discount"),
                ),
            )

            print(
                f"Recorded: {product['product_name']} "
                f"| Price: {product['price']:.2f}"
            )
            saved += 1

        connection.commit()

        print("\n--- Collection Summary ---")
        print(f"New observations: {saved}")
        print(f"Already collected today: {skipped}")
        print(f"Listings not found: {missing}")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    collect_price_history()
