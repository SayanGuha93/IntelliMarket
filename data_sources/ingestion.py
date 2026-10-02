from database.connection import get_connection
from ml.hybrid_matcher import hybrid_similarity


def get_existing_products(cursor):
    cursor.execute(
        """
        SELECT product_id, product_name, brand, model, category
        FROM products
        """
    )

    rows = cursor.fetchall()

    return [
        {
            "product_id": row[0],
            "product_name": row[1],
            "brand": row[2],
            "model": row[3],
            "category": row[4]
        }
        for row in rows
    ]


def find_hybrid_match(existing_products, product):
    best_product = None
    best_result = None

    for existing_product in existing_products:
        result = hybrid_similarity(
            existing_product,
            product
        )

        if best_result is None or result["final_score"] > best_result["final_score"]:
            best_result = result
            best_product = existing_product

    if best_result and best_result["decision"] == "MATCH":
        return best_product, best_result

    return None, best_result


def save_products(products):
    connection = get_connection()
    cursor = connection.cursor()

    existing_products = get_existing_products(cursor)

    matched_count = 0
    new_product_count = 0

    for product in products:
        matching_product, match_result = find_hybrid_match(
            existing_products,
            product
            )

        if matching_product:
            product_id = matching_product["product_id"]
            matched_count += 1

            print(
                f"Matched: {product['product_name']} "
                f"-> {matching_product['product_name']} "
                f"(score={match_result['final_score']:.4f})"
            )
        else:
            product_id = f"PROD_{len(existing_products) + 1}"

            cursor.execute(
                """
                INSERT INTO products (
                    product_id,
                    product_name,
                    brand,
                    model,
                    category
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    product["product_name"],
                    product.get("brand"),
                    product.get("model"),
                    product.get("category")
                )
            )

            existing_products.append(
                {
                    "product_id": product_id,
                    "product_name": product["product_name"],
                    "brand": product.get("brand"),
                    "model": product.get("model"),
                    "category": product.get("category")
                }
            )

            new_product_count += 1

            print(
                f"New product: {product['product_name']} "
                f"-> {product_id}"
            )

        cursor.execute(
            """
            SELECT listing_id
            FROM product_listings
            WHERE product_id = ?
            AND source = ?
            AND external_product_id = ?
            """,
            (
                product_id,
                product["source"],
                product["product_id"]
            )
        )

        existing_listing = cursor.fetchone()

        if existing_listing:
            listing_id = existing_listing[0]

            cursor.execute(
                """
                UPDATE product_listings
                SET seller = ?,
                    product_url = ?,
                    image_url = ?,
                    availability = ?,
                    last_seen = CURRENT_TIMESTAMP
                WHERE listing_id = ?
                """,
                (
                    product.get("seller"),
                    product.get("product_url"),
                    product.get("image_url"),
                    product.get("availability"),
                    listing_id
                )
            )
        else:
            cursor.execute(
                """
                INSERT INTO product_listings (
                    product_id,
                    source,
                    external_product_id,
                    seller,
                    product_url,
                    image_url,
                    availability
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    product["source"],
                    product["product_id"],
                    product.get("seller"),
                    product.get("product_url"),
                    product.get("image_url"),
                    product.get("availability")
                )
            )

            listing_id = cursor.lastrowid

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
                product.get("discount")
            )
        )

    connection.commit()
    connection.close()

    print()
    print(f"Matched existing products: {matched_count}")
    print(f"New canonical products: {new_product_count}")
    print(f"Total products processed: {len(products)}")