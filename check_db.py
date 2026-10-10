import sqlite3

conn = sqlite3.connect("prices.db")
cursor = conn.cursor()

cursor.execute("""
    SELECT
        pl.listing_id,
        p.product_id,
        p.product_name,
        pl.source,
        COUNT(ph.id) AS price_records
    FROM product_listings pl
    JOIN products p
        ON pl.product_id = p.product_id
    LEFT JOIN price_history ph
        ON pl.listing_id = ph.listing_id
    GROUP BY pl.listing_id
    ORDER BY price_records DESC
""")

rows = cursor.fetchall()

print("\nListing price history:")
print("-" * 80)

for row in rows:
    print(
        f"Listing ID: {row[0]} | "
        f"Product: {row[1]} | "
        f"Name: {row[2]} | "
        f"Source: {row[3]} | "
        f"Records: {row[4]}"
    )

conn.close()