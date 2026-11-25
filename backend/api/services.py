"""Read-only catalog queries and analysis calculations for the Django API."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3

from django.conf import settings


def catalog_path():
    configured = getattr(settings, "INTELLIMARKET_DB_PATH", "") or os.getenv("INTELLIMARKET_DB_PATH")
    path = Path(configured) if configured else Path(settings.PROJECT_ROOT) / "prices.db"
    return path if path.is_absolute() else Path(settings.PROJECT_ROOT) / path


@contextmanager
def catalog():
    path = catalog_path()
    if not path.is_file():
        raise FileNotFoundError("The IntelliMarket catalog database is unavailable.")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def one(sql, params=()):
    with catalog() as db:
        row = db.execute(sql, params).fetchone()
        return dict(row) if row else None


def all_rows(sql, params=()):
    with catalog() as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def product_list(search="", category="", limit=100):
    sql = "SELECT product_id, product_name, brand, model, category FROM products WHERE 1=1"
    params = []
    if search:
        sql += " AND (product_name LIKE ? OR brand LIKE ?)"
        params.extend([f"%{search}%"] * 2)
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY product_name LIMIT ?"
    params.append(limit)
    return all_rows(sql, params)


def product_detail(product_id):
    return one("SELECT product_id, product_name, brand, model, category, created_at FROM products WHERE product_id = ?", (product_id,))


def product_listings(product_id):
    return all_rows("""SELECT pl.listing_id, pl.source, pl.external_product_id, pl.seller,
        pl.product_url, pl.image_url, pl.availability, pl.first_seen, pl.last_seen
        FROM product_listings pl WHERE pl.product_id = ? ORDER BY pl.source, pl.listing_id""", (product_id,))


def product_history(product_id):
    return all_rows("""SELECT pl.listing_id, pl.source, pl.seller, ph.price, ph.mrp,
        ph.discount, ph.recorded_at FROM product_listings pl JOIN price_history ph
        ON ph.listing_id = pl.listing_id WHERE pl.product_id = ?
        ORDER BY ph.recorded_at, ph.id""", (product_id,))


def product_prices(product_id):
    return all_rows("""SELECT pl.listing_id, pl.source, pl.seller, pl.external_product_id, pl.product_url,
        ph.price, ph.mrp, ph.discount, ph.recorded_at FROM product_listings pl
        JOIN price_history ph ON ph.id = (SELECT ph2.id FROM price_history ph2
        WHERE ph2.listing_id = pl.listing_id ORDER BY ph2.recorded_at DESC, ph2.id DESC LIMIT 1)
        WHERE pl.product_id = ? ORDER BY ph.price""", (product_id,))


def price_insights(history):
    from analytics.price_history_analysis import analyze_history
    # Existing analysis helper expects source, external reference, price, time tuples.
    result = analyze_history([(row["source"], row["seller"], row["price"], row["recorded_at"]) for row in history])
    if not result:
        return {"available": False, "observation_count": 0, "reason": "No recorded price history is available."}
    return {"available": True, **result, "source": "prices.db recorded observations", "is_live": False}


def latest_price_comparison(product, prices):
    from analytics.price_comparison import analyze_prices
    rows = [(product["product_name"], row["source"], row["seller"], row["external_product_id"],
             row["price"], row["mrp"], row["discount"], row["recorded_at"]) for row in prices]
    result = analyze_prices(rows)
    if not result:
        return {"available": False, "reason": "No recorded listing prices are available."}
    cheapest, expensive = result["cheapest"], result["most_expensive"]
    return {"available": True, "listing_count": result["marketplaces"],
            "cheapest": {"source": cheapest[1], "seller": cheapest[2], "price": cheapest[4], "recorded_at": cheapest[7]},
            "most_expensive": {"source": expensive[1], "seller": expensive[2], "price": expensive[4], "recorded_at": expensive[7]},
            "price_difference": result["price_difference"],
            "percentage_difference_from_lowest": result["percentage_difference"], "is_live": False}


def book_list(query="", limit=100):
    sql = """SELECT volume_id, title, subtitle, authors, publisher, published_date, description,
        categories, isbn10, isbn13, thumbnail_url, preview_url, info_url, sale_country, saleability,
        is_ebook, google_list_price, google_list_currency, google_retail_price,
        google_retail_currency, updated_at FROM google_books_catalog"""
    params = []
    if query:
        sql += " WHERE title LIKE ? OR authors LIKE ? OR isbn10 = ? OR isbn13 = ?"
        params.extend([f"%{query}%", f"%{query}%", query, query])
    sql += " ORDER BY title LIMIT ?"
    params.append(limit)
    return all_rows(sql, params)


def book_detail(volume_id):
    return one("""SELECT volume_id, title, subtitle, authors, publisher, published_date, description,
        categories, isbn10, isbn13, thumbnail_url, preview_url, info_url, sale_country, saleability,
        is_ebook, google_list_price, google_list_currency, google_retail_price,
        google_retail_currency, updated_at FROM google_books_catalog WHERE volume_id = ?""", (volume_id,))


def book_history(volume_id):
    return all_rows("""SELECT volume_id, observed_at, sale_country, saleability, google_list_price,
        google_list_currency, google_retail_price, google_retail_currency
        FROM google_books_price_history WHERE volume_id = ? ORDER BY observed_at, id""", (volume_id,))


def crypto_list():
    return all_rows("""SELECT a.symbol, a.name, a.updated_at,
        (SELECT COUNT(*) FROM crypto_market_history h WHERE h.asset_id=a.id) observation_count
        FROM crypto_assets a ORDER BY a.symbol""")


def crypto_asset(symbol):
    return one("SELECT id, symbol, name, created_at, updated_at FROM crypto_assets WHERE symbol = ?", (symbol.upper(),))


def crypto_history(symbol, limit=500):
    rows = all_rows("""SELECT h.source_exchange, h.last, h.last_btc, h.lowest, h.highest,
        h.daily_change_percentage, h.provider_date, h.collected_at_utc
        FROM crypto_market_history h JOIN crypto_assets a ON a.id=h.asset_id
        WHERE a.symbol = ? ORDER BY h.collected_at_utc DESC, h.id DESC LIMIT ?""", (symbol.upper(), limit))
    return list(reversed(rows))


def json_value(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback
