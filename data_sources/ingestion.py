from database.connection import get_connection
from ml.hybrid_matcher import hybrid_similarity


def get_existing_products(cursor):
    cursor.execute(
        """
        SELECT product_id, product_name, brand, model, category
        FROM products
        """
    )

    return [
        {
            "product_id": row[0],
            "product_name": row[1],
            "brand": row[2],
            "model": row[3],
            "category": row[4]
        }
        for row in cursor.fetchall()
    ]


def find_hybrid_match(existing_products, product):
    best_product = None
    best_result = None

    for existing_product in existing_products:
        result = hybrid_similarity(existing_product, product)

        if best_result is None or result["final_score"] > best_result["final_score"]:
            best_result = result
            best_product = existing_product

    if best_result and best_result["decision"] == "MATCH":
        return best_product, best_result

    return None, best_result


def save_products(products):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        existing_products = get_existing_products(cursor)
        matched_count = 0
        new_product_count = 0
        new_listing_count = 0
        updated_listing_count = 0
        new_price_count = 0
        unchanged_price_count = 0

        for product in products:
            cursor.execute(
                """
                SELECT listing_id, product_id
                FROM product_listings
                WHERE source = ? AND external_product_id = ?
                """,
                (product["source"], product["product_id"])
            )
            existing_listing = cursor.fetchone()

            if existing_listing:
                listing_id, current_product_id = existing_listing

                cursor.execute(
                    """
                    SELECT product_id, product_name, brand, model, category
                    FROM products
                    WHERE product_id = ?
                    """,
                    (current_product_id,)
                )
                row = cursor.fetchone()

                if row:
                    matching_product = {
                        "product_id": row[0],
                        "product_name": row[1],
                        "brand": row[2],
                        "model": row[3],
                        "category": row[4]
                    }
                    match_result = None
                else:
                    raise ValueError(
                        f"Listing {listing_id} references missing product "
                        f"{current_product_id}"
                    )

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

                updated_listing_count += 1

            else:
                matching_product, match_result = find_hybrid_match(
                    existing_products, product
                )

                if matching_product:
                    matched_count += 1
                else:
                    cursor.execute(
                        "SELECT product_id FROM products"
                    )
                    existing_ids = {
                        row[0] for row in cursor.fetchall()
                    }

                    number = 1
                    while f"PROD_{number}" in existing_ids:
                        number += 1

                    product_id = f"PROD_{number}"

                    cursor.execute(
                        """
                        INSERT INTO products (
                            product_id, product_name, brand, model, category
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

                    matching_product = {
                        "product_id": product_id,
                        "product_name": product["product_name"],
                        "brand": product.get("brand"),
                        "model": product.get("model"),
                        "category": product.get("category")
                    }

                    existing_products.append(matching_product)
                    new_product_count += 1

                product_id = matching_product["product_id"]

                cursor.execute(
                    """
                    INSERT INTO product_listings (
                        product_id, source, external_product_id, seller,
                        product_url, image_url, availability
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
                new_listing_count += 1

            cursor.execute(
                """
                SELECT price, mrp, discount
                FROM price_history
                WHERE listing_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
                """,
                (listing_id,)
            )
            last_price = cursor.fetchone()

            current_price = (
                product["price"],
                product.get("mrp"),
                product.get("discount")
            )

            if last_price is None or tuple(last_price) != current_price:
                cursor.execute(
                    """
                    INSERT INTO price_history (
                        listing_id, price, mrp, discount
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (listing_id, *current_price)
                )
                new_price_count += 1
            else:
                unchanged_price_count += 1

        connection.commit()

        print(f"Matched existing products: {matched_count}")
        print(f"New canonical products: {new_product_count}")
        print(f"New listings: {new_listing_count}")
        print(f"Updated listings: {updated_listing_count}")
        print(f"New price observations: {new_price_count}")
        print(f"Unchanged prices skipped: {unchanged_price_count}")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()