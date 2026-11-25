import csv
from contextlib import closing
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    with (ROOT / "data" / f"{name}.csv").open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ.get("POWERBI_TEST_CATALOG", ROOT.parent / "rag_chatbot/artifacts/catalog.sqlite3"))
        cls.db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        cls.addClassCleanup(cls.db.close)
        cls.facts = load("fact_product")

    def test_grain_and_marketplace_product_counts(self):
        expected = set(self.db.execute("SELECT id, platform, source_id FROM products"))
        actual = {(int(r["product_id"]), r["marketplace"], r["source_product_id"]) for r in self.facts}
        self.assertEqual(expected, actual)
        self.assertEqual(len(actual), len(self.facts))
        self.assertEqual(len({r["product_id"] for r in self.facts}), len(actual))
        self.assertEqual(len({(r["marketplace"], r["source_product_id"]) for r in self.facts}), len(actual))

    def test_relationships_and_dimension_content(self):
        dimensions = {}
        for table, field in (("marketplace", "marketplace"), ("brand", "brand_id"), ("category", "category_id"), ("price_band", "price_band_id")):
            rows = load(f"dim_{table}")
            lookup = {r[field]: r for r in rows}
            self.assertEqual(len(rows), len(lookup))
            self.assertLessEqual({r[field] for r in self.facts}, lookup.keys())
            dimensions[table] = lookup
        sources = {str(r[0]): r[1:] for r in self.db.execute("""
            SELECT id, CASE WHEN brand IS NULL THEN '' ELSE coalesce(brand_key,'') END, category_path, coalesce(category_basis,''),
              CASE WHEN price_minor IS NULL THEN '0' WHEN price_minor < 50000 THEN '1'
                   WHEN price_minor < 100000 THEN '2' WHEN price_minor < 150000 THEN '3'
                   WHEN price_minor < 300000 THEN '4' ELSE '5' END
            FROM products
        """)}
        for fact in self.facts:
            brand, category, basis, band = sources[fact["product_id"]]
            self.assertEqual(dimensions["brand"][fact["brand_id"]]["brand_key"], brand)
            row = dimensions["category"][fact["category_id"]]
            parts = json.loads(category)
            self.assertEqual(row["category_path"], " > ".join(parts) if parts else "Unrecorded")
            self.assertEqual(row["category_basis"], basis if parts else "")
            self.assertEqual(fact["price_band_id"], band)

    def test_price_discount_rating_and_missing_values(self):
        query = """
            WITH base AS (
              SELECT *, CASE WHEN platform='flipkart' AND retail_price_minor>0 AND price_minor<=retail_price_minor
                          THEN retail_price_minor-price_minor END AS saving FROM products
            )
            SELECT id, price_field, price_minor, retail_price_minor,
                   CASE WHEN platform='flipkart' THEN price_minor END,
                   saving, 1.0*saving/retail_price_minor, rating, overall_rating, rating_count,
                   rating IS NOT NULL, overall_rating IS NOT NULL, rating_count IS NOT NULL,
                   price_minor IS NULL, retail_price_minor IS NULL, brand IS NULL OR coalesce(trim(brand_key),'')='',
                   json_array_length(category_path)=0, json(attributes)='{}', colour IS NULL,
                   observed_at IS NULL, EXISTS (SELECT 1 FROM json_each(conflicts)), observed_at, product_url, attributes
            FROM base
        """
        expected = {str(row[0]): row[1:] for row in self.db.execute(query)}
        fields = """recorded_price_field recorded_price retail_price discounted_price discount_amount discount_fraction
            rating overall_rating rating_count has_rating has_overall_rating has_rating_count missing_recorded_price
            missing_retail_price missing_brand missing_category missing_attributes missing_colour missing_observation_date
            has_conflicts observed_at product_url attributes_json""".split()
        for fact in self.facts:
            with self.subTest(product=fact["product_id"]):
                for index, (field, value) in enumerate(zip(fields, expected[fact["product_id"]])):
                    actual = fact[field]
                    if value is None:
                        self.assertEqual(actual, "")
                    elif 1 <= index <= 4:
                        self.assertEqual(Decimal(actual) * 100, value)
                    elif index == 5:
                        self.assertAlmostEqual(float(actual), value, places=14)
                    elif 6 <= index <= 7:
                        self.assertEqual(float(actual), value)
                    else:
                        self.assertEqual(actual, str(value))

    def test_lineage_preserves_all_source_rows(self):
        rows = load("source_lineage")
        expected = set(self.db.execute("""
            SELECT platform, record_number, coalesce(source_record_id,''), coalesce(CAST(product_id AS TEXT),''),
                   status, coalesce(reason,''), coalesce(CAST(duplicate_of AS TEXT),'') FROM source_records
        """))
        actual = {(r["marketplace"], int(r["record_number"]), r["source_record_id"], r["product_id"], r["status"],
                   r["reason"], r["duplicate_of_record_number"]) for r in rows}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(rows))
        self.assertEqual(len(rows), len({(r["marketplace"], r["record_number"]) for r in rows}))
        self.assertTrue(all(r["source_file"] == r["marketplace"] + ".csv" for r in rows))
        self.assertEqual({r["product_id"] for r in rows if r["status"] == "accepted"},
                         {r["product_id"] for r in self.facts})
