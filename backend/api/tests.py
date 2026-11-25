import sqlite3
import tempfile
import os
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from api.models import GoogleIdentity, RAGSessionOwner


class GoogleBooksApiTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("api.views.search_books")
    def test_live_search_requires_query_and_labels_provider(self, search):
        missing = self.client.get("/api/books/search/")
        self.assertEqual(missing.status_code, 400)
        search.assert_not_called()

        search.return_value = {"total_items": 1, "books": [{"volume_id": "v1"}]}
        response = self.client.get("/api/books/search/?q=testing&page_size=5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["provider"], "Google Books")
        search.assert_called_once_with("testing", start_index=0, max_results=5)

    def test_stored_catalog_and_google_price_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "prices.db"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.executescript("""
                    CREATE TABLE google_books_catalog (
                        volume_id TEXT PRIMARY KEY, title TEXT, subtitle TEXT, authors TEXT,
                        publisher TEXT, published_date TEXT, description TEXT, categories TEXT,
                        isbn10 TEXT, isbn13 TEXT, thumbnail_url TEXT, preview_url TEXT, info_url TEXT,
                        sale_country TEXT, saleability TEXT, is_ebook INTEGER, google_list_price REAL,
                        google_list_currency TEXT, google_retail_price REAL, google_retail_currency TEXT,
                        updated_at TEXT
                    );
                    CREATE TABLE google_books_price_history (
                        id INTEGER PRIMARY KEY, volume_id TEXT, observed_at TEXT, sale_country TEXT,
                        saleability TEXT, google_list_price REAL, google_list_currency TEXT,
                        google_retail_price REAL, google_retail_currency TEXT
                    );
                    INSERT INTO google_books_catalog (volume_id, title, authors, categories)
                    VALUES ('v1', 'Test Book', '["Writer"]', '[]');
                    INSERT INTO google_books_price_history (
                        volume_id, observed_at, google_retail_price, google_retail_currency
                    ) VALUES ('v1', '2025-01-01', 5.25, 'USD');
                """)
            with override_settings(INTELLIMARKET_DB_PATH=str(db_path)):
                books = self.client.get("/api/books/?q=Test")
                history = self.client.get("/api/books/v1/price-history/")
            self.assertEqual(books.data["books"][0]["volume_id"], "v1")
            self.assertEqual(history.data["price_source"], "Google Books eBookstore")
            self.assertEqual(history.data["history"][0]["google_retail_price"], 5.25)


class AnalysisApiTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "prices.db"
        with sqlite3.connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE products (product_id TEXT PRIMARY KEY, product_name TEXT, brand TEXT, model TEXT, category TEXT, created_at TEXT);
                CREATE TABLE product_listings (listing_id INTEGER PRIMARY KEY, product_id TEXT, source TEXT, external_product_id TEXT, seller TEXT, product_url TEXT, image_url TEXT, availability TEXT, first_seen TEXT, last_seen TEXT);
                CREATE TABLE price_history (id INTEGER PRIMARY KEY, listing_id INTEGER, price REAL, mrp REAL, discount REAL, recorded_at TEXT);
                CREATE TABLE google_books_catalog (volume_id TEXT PRIMARY KEY, title TEXT, subtitle TEXT, authors TEXT, publisher TEXT, published_date TEXT, description TEXT, categories TEXT, isbn10 TEXT, isbn13 TEXT, thumbnail_url TEXT, preview_url TEXT, info_url TEXT, sale_country TEXT, saleability TEXT, is_ebook INTEGER, google_list_price REAL, google_list_currency TEXT, google_retail_price REAL, google_retail_currency TEXT, updated_at TEXT);
                CREATE TABLE google_books_price_history (id INTEGER PRIMARY KEY, volume_id TEXT, observed_at TEXT, sale_country TEXT, saleability TEXT, google_list_price REAL, google_list_currency TEXT, google_retail_price REAL, google_retail_currency TEXT);
                CREATE TABLE crypto_assets (id INTEGER PRIMARY KEY, symbol TEXT, name TEXT, created_at TEXT, updated_at TEXT);
                CREATE TABLE crypto_market_history (id INTEGER PRIMARY KEY, asset_id INTEGER, source_exchange TEXT, last REAL, last_btc REAL, lowest REAL, highest REAL, daily_change_percentage REAL, provider_date TEXT, collected_at_utc TEXT, raw_payload_json TEXT);
                INSERT INTO products VALUES ('p1','Widget','Acme','M1','tools','2025-01-01');
                INSERT INTO product_listings VALUES (1,'p1','shop-a','x1','seller',NULL,NULL,'in stock','2025-01-01','2025-01-01');
                INSERT INTO price_history VALUES (1,1,10,12,2,'2025-01-01');
                INSERT INTO price_history VALUES (2,1,8,12,4,'2025-02-01');
                INSERT INTO google_books_catalog (volume_id,title,authors,categories,google_retail_price,google_retail_currency) VALUES ('v1','Book','["Writer"]','[]',5,'USD');
                INSERT INTO google_books_price_history VALUES (1,'v1','2025-01-01','US','FOR_SALE',7,'USD',5,'USD');
                INSERT INTO crypto_assets VALUES (1,'BTC','Bitcoin','2025-01-01','2025-01-01');
                INSERT INTO crypto_market_history VALUES (1,1,'exchange-a',100,0.01,90,110,1,'provider-date','2025-01-01T00:00:00Z','{}');
                INSERT INTO crypto_market_history VALUES (2,1,'exchange-a',110,0.01,100,120,2,'provider-date-2','2025-01-02T00:00:00Z','{}');
            """)
        self.settings = override_settings(INTELLIMARKET_DB_PATH=str(self.db_path))
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="tester", email="tester@example.com")

    def test_analysis_and_chat_endpoints_require_authentication(self):
        for path in ("/api/analysis/products/", "/api/analysis/books/search/?q=test", "/api/chat/session/"):
            self.assertIn(self.client.get(path).status_code, (401, 403))

    def test_product_analysis_uses_existing_catalog(self):
        self.client.force_authenticate(self.user)
        detail = self.client.get("/api/analysis/products/p1/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["product"]["product_name"], "Widget")
        insights = self.client.get("/api/analysis/products/p1/insights/")
        self.assertEqual(insights.data["insights"]["lowest_price"], 8.0)
        self.assertFalse(insights.data["insights"]["is_live"])

    def test_books_and_crypto_analysis_are_database_backed(self):
        self.client.force_authenticate(self.user)
        books = self.client.get("/api/analysis/books/v1/")
        self.assertEqual(books.data["book"]["title"], "Book")
        book_history = self.client.get("/api/analysis/books/v1/history/")
        self.assertEqual(book_history.data["price_source"], "Google Books eBookstore")
        crypto = self.client.get("/api/analysis/crypto/BTC/insights/")
        self.assertEqual(crypto.data["by_exchange"][0]["latest_recorded_price"], 110.0)
        self.assertFalse(crypto.data["is_live"])

    def test_prediction_is_explicitly_unavailable_and_bad_id_is_rejected(self):
        self.client.force_authenticate(self.user)
        prediction = self.client.get("/api/analysis/products/p1/prediction/")
        self.assertFalse(prediction.data["available"])
        invalid = self.client.get("/api/analysis/products/bad%20id/")
        self.assertEqual(invalid.status_code, 400)

    @patch("api.views.requests.request")
    def test_rag_gateway_rejects_another_users_session(self, upstream):
        self.client.force_authenticate(self.user)
        session_id = "bd835e23-2c4f-4f2c-b1d9-2f12ef6f64e1"
        other = get_user_model().objects.create_user(username="other", email="other@example.com")
        RAGSessionOwner.objects.create(session_id=session_id, user=other)
        response = self.client.get(f"/api/chat/session/{session_id}/")
        self.assertEqual(response.status_code, 404)
        upstream.assert_not_called()

    def test_unconfigured_powerbi_does_not_call_microsoft(self):
        self.client.force_authenticate(self.user)
        with patch.dict(os.environ, {"PBI_REPORT_IDS": ""}, clear=False):
            response = self.client.get("/api/powerbi/reports/report-1/")
        self.assertEqual(response.status_code, 404)

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_google_login_creates_user_reuses_subject_and_logout_ends_session(self, verify):
        verify.return_value = {"iss": "https://accounts.google.com", "sub": "stable-google-subject",
            "email": "new@example.com", "email_verified": True, "given_name": "New", "family_name": "User"}
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "test-client-id"}, clear=False):
            first = self.client.post("/api/auth/google/", {"credential": "a" * 30}, format="json")
            second = self.client.post("/api/auth/google/", {"credential": "b" * 30}, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        user = get_user_model().objects.get(email="new@example.com")
        self.assertEqual(GoogleIdentity.objects.filter(subject="stable-google-subject").count(), 1)
        self.assertEqual(first.data["user"]["id"], user.pk)
        self.assertEqual(second.data["user"]["id"], user.pk)
        self.assertTrue(self.client.get("/api/auth/me/").data["authenticated"])
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 200)
        self.assertFalse(self.client.get("/api/auth/me/").data["authenticated"])

    def test_powerbi_email_allowlist_is_enforced(self):
        self.client.force_authenticate(self.user)
        with patch.dict(os.environ, {"POWERBI_ALLOWED_USER_EMAILS": "only@example.com", "PBI_REPORT_IDS": "report-1"}, clear=False):
            response = self.client.get("/api/powerbi/reports/")
        self.assertEqual(response.status_code, 403)

    @patch("api.views._powerbi_request")
    def test_powerbi_embed_token_returns_only_embed_configuration(self, upstream):
        self.client.force_authenticate(self.user)
        upstream.side_effect = [
            ({"id": "report-1", "embedUrl": "https://app.powerbi.com/reportEmbed", "datasetId": "dataset-1"}, None),
            ({"token": "mock-embed-token", "expiration": "provider-issued-expiry"}, None),
        ]
        with patch.dict(os.environ, {"PBI_REPORT_IDS": "report-1", "POWERBI_ALLOWED_USER_EMAILS": ""}, clear=False):
            response = self.client.post("/api/powerbi/reports/report-1/embed-token/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["token_type"], "Embed")
        self.assertEqual(response.data["token"], "mock-embed-token")
        self.assertNotIn("client_secret", response.data)
        self.assertEqual(upstream.call_count, 2)
