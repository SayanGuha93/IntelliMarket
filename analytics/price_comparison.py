from database.connection import get_connection

def compare_product(product_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            p.product_name,
            pl.source,
            pl.seller,
            pl.external_product_id,
            ph.price,
            ph.mrp,
            ph.discount,
            ph.recorded_at
        FROM products p
        JOIN product_listings pl
            ON p.product_id = pl.product_id
        JOIN price_history ph
            ON pl.listing_id = ph.listing_id
        WHERE p.product_id = ?
        ORDER BY ph.price ASC
        """,
        (product_id,)
    )

    rows = cursor.fetchall()
    connection.close()

    return rows

def analyze_prices(rows):
    if not rows:
        return None

    prices = [row[4] for row in rows]

    cheapest = min(rows, key=lambda row: row[4])
    expensive = max(rows, key=lambda row: row[4])

    cheapest_price = cheapest[4]
    expensive_price = expensive[4]

    difference = expensive_price - cheapest_price

    percentage_difference = 0

    if cheapest_price > 0:
        percentage_difference = (difference / cheapest_price) * 100

    return {
        "product_name": rows[0][0],
        "marketplaces": len(rows),
        "cheapest": cheapest,
        "most_expensive": expensive,
        "price_difference": difference,
        "percentage_difference": percentage_difference
    }

if __name__ == "__main__":
    product_id = input("Enter product ID: ")

    rows = compare_product(product_id)
    analysis = analyze_prices(rows)

    if not analysis:
        print("Product not found.")
    else:
        print()
        print("Product:", analysis["product_name"])
        print("Marketplaces:", analysis["marketplaces"])
        print("Cheapest:", analysis["cheapest"][1])
        print("Cheapest Price:", analysis["cheapest"][4])
        print("Most Expensive:", analysis["most_expensive"][1])
        print("Most Expensive Price:", analysis["most_expensive"][4])
        print("Price Difference:", round(analysis["price_difference"], 2))
        print(
            "Percentage Difference:",
            round(analysis["percentage_difference"], 2),
            "%"
        )