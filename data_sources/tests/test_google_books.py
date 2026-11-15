import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from data_sources.google_books import (
    GoogleBooksError,
    normalize_volume,
    save_catalog_records,
    search_books,
)


VOLUME = {
    "id": "volume-123",
    "volumeInfo": {
        "title": "Example Book",
        "authors": ["A. Author"],
        "industryIdentifiers": [
            {"type": "ISBN_13", "identifier": "9780000000001"}
        ],
        "imageLinks": {"thumbnail": "https://example.test/cover.jpg"},
    },
    "saleInfo": {
        "country": "US",
        "saleability": "FOR_SALE",
        "isEbook": True,
        "retailPrice": {"amount": 4.99, "currencyCode": "USD"},
    },
}


class GoogleBooksTests(unittest.TestCase):
    def test_normalize_keeps_google_price_provenance_and_missing_list_price(self):
        book = normalize_volume(VOLUME)
        self.assertEqual(book["isbn13"], "9780000000001")
        self.assertEqual(book["google_retail_price"], 4.99)
        self.assertEqual(book["google_retail_currency"], "USD")
        self.assertIsNone(book["google_list_price"])
        self.assertEqual(book["price_source"], "Google Books eBookstore")

    def test_search_uses_pagination_and_normalizes_items(self):
        response = Mock()
        response.json.return_value = {"totalItems": 1, "items": [VOLUME]}
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response

        result = search_books("example", start_index=20, max_results=5, session=session)

        self.assertEqual(result["total_items"], 1)
        self.assertEqual(result["books"][0]["volume_id"], "volume-123")
        self.assertEqual(session.get.call_args.kwargs["params"]["startIndex"], 20)
        self.assertEqual(session.get.call_args.kwargs["timeout"], 10)

    def test_search_rejects_empty_query_and_invalid_page_size(self):
        with self.assertRaises(ValueError):
            search_books(" ")
        with self.assertRaises(ValueError):
            search_books("book", max_results=41)

    def test_search_wraps_http_and_json_errors(self):
        response = Mock()
        response.raise_for_status.side_effect = ValueError("bad response")
        session = Mock()
        session.get.return_value = response
        with self.assertRaises(GoogleBooksError):
            search_books("book", session=session)

    def test_catalog_upsert_runs_on_separate_additive_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "prices.sqlite3"
            with sqlite3.connect(db_path) as connection:
                migration = Path(__file__).resolve().parents[2] / "database" / "migrations" / "001_google_books_catalog.sql"
                connection.executescript(migration.read_text(encoding="utf-8"))

            book = normalize_volume(VOLUME)
            save_catalog_records([book], database_path=db_path)
            book["title"] = "Updated Example Book"
            save_catalog_records([book], database_path=db_path)

            with sqlite3.connect(db_path) as connection:
                row = connection.execute(
                    "SELECT title, authors, google_retail_price, google_retail_currency FROM google_books_catalog WHERE volume_id = ?",
                    ("volume-123",),
                ).fetchone()
                history_count = connection.execute(
                    "SELECT COUNT(*) FROM google_books_price_history WHERE volume_id = ?",
                    ("volume-123",),
                ).fetchone()[0]
            self.assertEqual(row[0], "Updated Example Book")
            self.assertEqual(json.loads(row[1]), ["A. Author"])
            self.assertEqual(row[2:], (4.99, "USD"))
            self.assertEqual(history_count, 1)


if __name__ == "__main__":
    unittest.main()
