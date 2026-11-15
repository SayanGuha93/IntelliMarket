import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from . import views


class GoogleBooksApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("api.views.search_books")
    def test_live_search_requires_query_and_labels_provider(self, search):
        missing = views.search_google_books(self.factory.get("/api/books/search/"))
        self.assertEqual(missing.status_code, 400)
        search.assert_not_called()

        search.return_value = {"total_items": 1, "books": [{"volume_id": "v1"}]}
        response = views.search_google_books(
            self.factory.get("/api/books/search/?q=testing&page_size=5")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["provider"], "Google Books")
        search.assert_called_once_with("testing", start_index=0, max_results=5)

    def test_stored_catalog_and_google_price_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "backend").mkdir()
            db_path = root / "prices.db"
            with sqlite3.connect(db_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE google_books_catalog (
                        volume_id TEXT PRIMARY KEY, title TEXT, subtitle TEXT,
                        authors TEXT, publisher TEXT, published_date TEXT,
                        description TEXT, categories TEXT, isbn10 TEXT, isbn13 TEXT,
                        thumbnail_url TEXT, preview_url TEXT, info_url TEXT,
                        sale_country TEXT, saleability TEXT, is_ebook INTEGER,
                        google_list_price REAL, google_list_currency TEXT,
                        google_retail_price REAL, google_retail_currency TEXT,
                        updated_at TEXT
                    );
                    CREATE TABLE google_books_price_history (
                        id INTEGER PRIMARY KEY, volume_id TEXT, observed_at TEXT,
                        sale_country TEXT, saleability TEXT,
                        google_list_price REAL, google_list_currency TEXT,
                        google_retail_price REAL, google_retail_currency TEXT
                    );
                    INSERT INTO google_books_catalog (volume_id, title, authors)
                    VALUES ('v1', 'Test Book', '["Writer"]');
                    INSERT INTO google_books_price_history (
                        volume_id, observed_at, google_retail_price, google_retail_currency
                    ) VALUES ('v1', '2025-01-01', 5.25, 'USD');
                    """
                )

            with override_settings(BASE_DIR=root / "backend"):
                books = views.get_stored_google_books(
                    self.factory.get("/api/books/?q=Test")
                )
                history = views.get_google_books_price_history(
                    self.factory.get("/api/books/v1/price-history/"), "v1"
                )

            books_data = json.loads(books.content)
            history_data = json.loads(history.content)
            self.assertEqual(books_data["books"][0]["volume_id"], "v1")
            self.assertEqual(history_data["price_source"], "Google Books eBookstore")
            self.assertEqual(history_data["history"][0]["google_retail_price"], 5.25)
