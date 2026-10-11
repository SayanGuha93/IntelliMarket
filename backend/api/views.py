import sqlite3
from pathlib import Path

from django.http import JsonResponse
from django.conf import settings



def get_products(request):
    db_path = Path(settings.BASE_DIR).parent / "prices.db"
    search = request.GET.get("search", "").strip()
    category = request.GET.get("category", "").strip()

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        query = """
            SELECT
                p.product_id,
                p.product_name,
                p.brand,
                p.model,
                p.category
            FROM products p
            WHERE 1=1
        """
        params = []

        if search:
            query += " AND (p.product_name LIKE ? OR p.brand LIKE ?)"
            term = f"%{search}%"
            params.extend([term, term])

        if category:
            query += " AND p.category = ?"
            params.append(category)

        query += " ORDER BY p.product_name"

        rows = conn.execute(query, params).fetchall()
        products = [dict(row) for row in rows]
        conn.close()

        return JsonResponse({
            "count": len(products),
            "products": products
        })

    except sqlite3.Error as error:
        return JsonResponse({"error": str(error)}, status=500)

def compare_prices(request):
    db_path = Path(settings.BASE_DIR).parent / "prices.db"

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT
                p.product_id,
                p.product_name,
                pl.source,
                pl.seller,
                pl.product_url,
                ph.price,
                ph.mrp,
                ph.discount,
                ph.recorded_at
            FROM products p
            JOIN product_listings pl
                ON p.product_id = pl.product_id
            JOIN price_history ph
                ON pl.listing_id = ph.listing_id
            WHERE ph.recorded_at = (
                SELECT MAX(ph2.recorded_at)
                FROM price_history ph2
                WHERE ph2.listing_id = pl.listing_id
            )
            ORDER BY p.product_name, ph.price
        """).fetchall()

        results = [dict(row) for row in rows]
        conn.close()

        return JsonResponse({
            "count": len(results),
            "comparisons": results
        })

    except sqlite3.Error as error:
        return JsonResponse({"error": str(error)}, status=500)

def get_price_history(request, listing_id):
    db_path = Path(settings.BASE_DIR).parent / "prices.db"

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT
                listing_id,
                price,
                mrp,
                discount,
                recorded_at
            FROM price_history
            WHERE listing_id = ?
            ORDER BY recorded_at ASC, id ASC
        """, (listing_id,)).fetchall()

        history = [dict(row) for row in rows]
        conn.close()

        return JsonResponse({
            "listing_id": listing_id,
            "count": len(history),
            "history": history
        })

    except sqlite3.Error as error:
        return JsonResponse({"error": str(error)}, status=500)


def get_analytics(request):
    db_path = Path(settings.BASE_DIR).parent / "prices.db"

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        summary = conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM products) AS total_products,
                (SELECT COUNT(*) FROM product_listings) AS total_listings,
                (SELECT COUNT(*) FROM price_history) AS total_observations,
                (SELECT COUNT(DISTINCT source) FROM product_listings) AS marketplace_sources
        """).fetchone()

        prices = conn.execute("""
            SELECT
                pl.listing_id,
                pl.source,
                ph.price
            FROM product_listings pl
            JOIN price_history ph ON ph.id = (
                SELECT ph2.id
                FROM price_history ph2
                WHERE ph2.listing_id = pl.listing_id
                ORDER BY ph2.recorded_at DESC, ph2.id DESC
                LIMIT 1
            )
        """).fetchall()

        conn.close()

        price_values = [row["price"] for row in prices if row["price"] is not None]

        return JsonResponse({
            "summary": dict(summary),
            "listings_with_latest_prices": len(price_values),
            "average_latest_price": (
                round(sum(price_values) / len(price_values), 2)
                if price_values else None
            ),
            "lowest_latest_price": min(price_values) if price_values else None,
            "highest_latest_price": max(price_values) if price_values else None
        })

    except sqlite3.Error as error:
        return JsonResponse({"error": str(error)}, status=500)


def get_category_analytics(request):
    db_path = Path(settings.BASE_DIR).parent / "prices.db"

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT
                p.category,
                COUNT(DISTINCT p.product_id) AS product_count,
                COUNT(DISTINCT pl.listing_id) AS listing_count,
                ROUND(AVG(latest.price), 2) AS average_latest_price,
                MIN(latest.price) AS lowest_latest_price,
                MAX(latest.price) AS highest_latest_price
            FROM products p
            LEFT JOIN product_listings pl
                ON pl.product_id = p.product_id
            LEFT JOIN (
                SELECT ph.listing_id, ph.price
                FROM price_history ph
                JOIN (
                    SELECT listing_id, MAX(id) AS latest_id
                    FROM price_history
                    GROUP BY listing_id
                ) recent ON recent.latest_id = ph.id
            ) latest ON latest.listing_id = pl.listing_id
            GROUP BY p.category
            ORDER BY p.category
        """).fetchall()

        conn.close()

        return JsonResponse({
            "categories": [dict(row) for row in rows]
        })

    except sqlite3.Error as error:
        return JsonResponse({"error": str(error)}, status=500)

