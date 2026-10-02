from database.connection import get_connection

def get_price_history(product_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            pl.source,
            pl.external_product_id,
            ph.price,
            ph.recorded_at
        FROM product_listings pl
        JOIN price_history ph
            ON pl.listing_id = ph.listing_id
        WHERE pl.product_id = ?
        ORDER BY ph.recorded_at
        """,
        (product_id,)
    )

    rows = cursor.fetchall()
    connection.close()

    return rows

def analyze_history(rows):
    if not rows:
        return None

    prices = [row[2] for row in rows]

    return {
        "observations": len(prices),
        "lowest_price": min(prices),
        "highest_price": max(prices),
        "average_price": sum(prices) / len(prices),
        "first_price": prices[0],
        "latest_price": prices[-1],
        "price_change": prices[-1] - prices[0]
    }

if __name__ == "__main__":
    product_id = input("Enter product ID: ")

    rows = get_price_history(product_id)
    analysis = analyze_history(rows)

    if not analysis:
        print("No price history found.")
    else:
        print()
        print("Observations:", analysis["observations"])
        print("Lowest Price:", round(analysis["lowest_price"], 2))
        print("Highest Price:", round(analysis["highest_price"], 2))
        print("Average Price:", round(analysis["average_price"], 2))
        print("First Price:", round(analysis["first_price"], 2))
        print("Latest Price:", round(analysis["latest_price"], 2))
        print("Price Change:", round(analysis["price_change"], 2))