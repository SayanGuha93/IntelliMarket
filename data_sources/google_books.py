"""Google Books API client and catalog ingestion helpers.

Google Books saleInfo is kept explicitly separate from third-party offers.
"""

from __future__ import annotations

import os
import sqlite3

import requests

API_URL = "https://www.googleapis.com/books/v1/volumes"
DEFAULT_TIMEOUT = 10
MAX_RESULTS = 40


class GoogleBooksError(RuntimeError):
    """Raised when the Google Books API cannot provide a valid response."""


def search_books(query, *, start_index=0, max_results=10, session=None):
    """Search public Google Books volumes and return normalized records."""
    query = (query or "").strip()
    if not query:
        raise ValueError("A non-empty search query is required.")
    if start_index < 0:
        raise ValueError("start_index must be zero or greater.")
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS}.")

    client = session or requests
    params = {
        "q": query,
        "startIndex": start_index,
        "maxResults": max_results,
        "printType": "books",
        "projection": "lite",
    }
    api_key = os.getenv("GOOGLE_BOOKS_API_KEY")
    if api_key:
        params["key"] = api_key

    try:
        response = client.get(API_URL, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise GoogleBooksError(f"Google Books search failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise GoogleBooksError("Google Books returned an invalid response.")

    return {
        "total_items": int(payload.get("totalItems") or 0),
        "start_index": start_index,
        "max_results": max_results,
        "books": [normalize_volume(item) for item in payload.get("items", [])],
    }


def normalize_volume(volume):
    """Convert a Google volume to a stable, JSON-safe record."""
    info = volume.get("volumeInfo") or {}
    sale = volume.get("saleInfo") or {}
    identifiers = {
        entry.get("type"): entry.get("identifier")
        for entry in info.get("industryIdentifiers", [])
        if entry.get("type") and entry.get("identifier")
    }
    image_links = info.get("imageLinks") or {}

    def amount(field):
        value = sale.get(field) or {}
        return value.get("amount"), value.get("currencyCode")

    list_amount, list_currency = amount("listPrice")
    retail_amount, retail_currency = amount("retailPrice")
    return {
        "volume_id": volume.get("id"),
        "title": info.get("title") or "Untitled",
        "subtitle": info.get("subtitle"),
        "authors": info.get("authors") or [],
        "publisher": info.get("publisher"),
        "published_date": info.get("publishedDate"),
        "description": info.get("description"),
        "categories": info.get("categories") or [],
        "isbn10": identifiers.get("ISBN_10"),
        "isbn13": identifiers.get("ISBN_13"),
        "thumbnail_url": image_links.get("thumbnail") or image_links.get("smallThumbnail"),
        "preview_url": info.get("previewLink"),
        "info_url": info.get("infoLink"),
        "sale_country": sale.get("country"),
        "saleability": sale.get("saleability"),
        "is_ebook": sale.get("isEbook"),
        "google_list_price": list_amount,
        "google_list_currency": list_currency,
        "google_retail_price": retail_amount,
        "google_retail_currency": retail_currency,
        "price_source": "Google Books eBookstore",
    }


def save_catalog_records(books, database_path=None):
    """Upsert catalog metadata into the additive google_books_catalog table."""
    if database_path is None:
        from database.connection import DATABASE_PATH
        database_path = DATABASE_PATH
    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        for book in books:
            if not book.get("volume_id"):
                continue
            connection.execute(
                """INSERT INTO google_books_catalog (
                    volume_id, title, subtitle, authors, publisher,
                    published_date, description, categories, isbn10, isbn13,
                    thumbnail_url, preview_url, info_url, sale_country,
                    saleability, is_ebook, google_list_price,
                    google_list_currency, google_retail_price,
                    google_retail_currency
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(volume_id) DO UPDATE SET
                    title=excluded.title, subtitle=excluded.subtitle,
                    authors=excluded.authors, publisher=excluded.publisher,
                    published_date=excluded.published_date,
                    description=excluded.description, categories=excluded.categories,
                    isbn10=excluded.isbn10, isbn13=excluded.isbn13,
                    thumbnail_url=excluded.thumbnail_url, preview_url=excluded.preview_url,
                    info_url=excluded.info_url, sale_country=excluded.sale_country,
                    saleability=excluded.saleability, is_ebook=excluded.is_ebook,
                    google_list_price=excluded.google_list_price,
                    google_list_currency=excluded.google_list_currency,
                    google_retail_price=excluded.google_retail_price,
                    google_retail_currency=excluded.google_retail_currency,
                    updated_at=CURRENT_TIMESTAMP""",
                (
                    book["volume_id"], book["title"], book.get("subtitle"),
                    _json(book.get("authors", [])), book.get("publisher"),
                    book.get("published_date"), book.get("description"),
                    _json(book.get("categories", [])), book.get("isbn10"),
                    book.get("isbn13"), book.get("thumbnail_url"),
                    book.get("preview_url"), book.get("info_url"),
                    book.get("sale_country"), book.get("saleability"),
                    None if book.get("is_ebook") is None else int(book["is_ebook"]),
                    book.get("google_list_price"), book.get("google_list_currency"),
                    book.get("google_retail_price"), book.get("google_retail_currency"),
                ),
            )
            current_price = (
                book.get("sale_country"), book.get("saleability"),
                book.get("google_list_price"), book.get("google_list_currency"),
                book.get("google_retail_price"), book.get("google_retail_currency"),
            )
            if current_price[2] is not None or current_price[4] is not None:
                previous = connection.execute(
                    """SELECT sale_country, saleability, google_list_price,
                              google_list_currency, google_retail_price,
                              google_retail_currency
                       FROM google_books_price_history
                       WHERE volume_id = ? ORDER BY observed_at DESC, id DESC LIMIT 1""",
                    (book["volume_id"],),
                ).fetchone()
                if previous is None or tuple(previous) != current_price:
                    connection.execute(
                        """INSERT INTO google_books_price_history (
                               volume_id, sale_country, saleability,
                               google_list_price, google_list_currency,
                               google_retail_price, google_retail_currency
                           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (book["volume_id"], *current_price),
                    )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def ingest_books(query, *, max_pages=1, page_size=40, database_path=None):
    """Fetch pages and persist catalog records; never invent missing prices."""
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1.")
    records = []
    for page in range(max_pages):
        result = search_books(query, start_index=page * page_size, max_results=page_size)
        records.extend(result["books"])
        if page * page_size + page_size >= result["total_items"]:
            break
    save_catalog_records(records, database_path=database_path)
    return records


def _json(value):
    import json
    return json.dumps(value, ensure_ascii=False)
