import json
import sqlite3
import unittest
from collections import Counter
from contextlib import closing
from pathlib import Path

from intellimarket_rag.catalog import search
from intellimarket_rag.ingest import normalize, parse_attributes, parse_specs, records, sha256


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "artifacts" / "catalog.sqlite3"


class PreprocessingTests(unittest.TestCase):
    def test_source_schema_rejects_wrong_platform_file(self):
        with self.assertRaisesRegex(ValueError, "missing headers"):
            next(records(ROOT / "data" / "myntra.csv", "flipkart"))

    def test_flipkart_real_specifications_and_timestamp(self):
        _, raw = next(records(ROOT / "data" / "flipkart.csv", "flipkart"))
        result = normalize("flipkart", raw, Counter())
        self.assertEqual(result["attributes"]["fabric"], ["Cotton Lycra"])
        self.assertIn("3 shorts", result["notes"])
        self.assertEqual(result["source_id"], "SRTEH2FF9KEDEFGF")
        self.assertEqual(result["category_basis"], "source_category_tree")
        self.assertEqual(result["observed_at"], "2016-03-25T22:59:23+00:00")
        self.assertIsNone(result["rating"])

    def test_myntra_real_attributes_description_and_identity(self):
        _, raw = next(records(ROOT / "data" / "myntra.csv", "myntra"))
        result = normalize("myntra", raw, Counter())
        self.assertEqual(result["source_id"], "17048614")
        self.assertEqual(result["attributes"]["bottom fabric"], ["Viscose Rayon"])
        self.assertNotIn("character", result["attributes"])
        self.assertNotIn("<", result["description"])
        self.assertEqual(result["categories"], ["Kurtas"])
        self.assertEqual(result["category_basis"], "inferred_from_title")
        self.assertIsNone(result["observed_at"])

    def test_parsers_reject_non_data_expressions(self):
        with self.assertRaises((ValueError, SyntaxError)):
            parse_attributes("object()")
        with self.assertRaises(ValueError):
            parse_specs('{"product_specification"=>Kernel.exec()}')

    def test_flipkart_single_object_specification_from_csv(self):
        source = records(ROOT / "data" / "flipkart.csv", "flipkart")
        with closing(source):
            raw = next(row for _, row in source if 'croco leather material' in row["product_specifications"]
                       and row["product_specifications"].startswith('{"product_specification"=>{'))
        self.assertEqual(parse_specs(raw["product_specifications"]),
                         ({"body material": ["croco leather material"]}, []))


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((DB.parent / "ingestion_report.json").read_text(encoding="utf-8"))

    def query(self, sql, args=()):
        with closing(sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)) as connection:
            return connection.execute(sql, args).fetchall()

    def test_integrity_and_lineage_reconcile_to_original_files(self):
        self.assertEqual(self.query("PRAGMA integrity_check"), [("ok",)])
        self.assertEqual(self.query("PRAGMA foreign_key_check"), [])
        self.assertEqual(
            self.query("SELECT COUNT(*) FROM products p LEFT JOIN product_fts f ON p.id=f.rowid WHERE f.rowid IS NULL"),
            [(0,)],
        )
        for platform, result in self.report["sources"].items():
            path = ROOT / "data" / result["source_file"]
            self.assertEqual(sha256(path), self.report["sha256_before"][platform])
            actual = dict(self.query(
                "SELECT status, count(*) FROM source_records WHERE platform = ? GROUP BY status",
                (platform,),
            ))
            self.assertEqual(sum(actual.values()), result["counts"]["raw"])
            for status in ("accepted", "excluded", "duplicate"):
                self.assertEqual(actual.get(status, 0), result["counts"][status])

    def test_duplicate_and_conflicting_rows_remain_traceable(self):
        counts = self.query("""
            SELECT count(*) FROM source_records duplicate
            JOIN source_records original ON original.platform = duplicate.platform
                 AND original.record_number = duplicate.duplicate_of
                 AND original.product_id = duplicate.product_id
                 AND original.raw_json = duplicate.raw_json
            WHERE duplicate.status = 'duplicate' AND original.status = 'accepted'
        """)
        self.assertEqual(counts, [(self.report["sources"]["myntra"]["counts"]["duplicate"],)])
        conflict = self.query("SELECT id, conflicts FROM products WHERE conflicts <> '{}' LIMIT 1")
        self.assertTrue(conflict)
        product_id, fields = conflict[0]
        lineage = set(self.query("SELECT record_number FROM source_records WHERE product_id = ?", (product_id,)))
        for values in json.loads(fields).values():
            self.assertGreaterEqual(len(values), 2)
            for item in values:
                self.assertTrue({(record,) for record in item["records"]} <= lineage)

    def test_combined_filters_against_sql_order_and_membership(self):
        expected = self.query("""
            SELECT id FROM products
            WHERE platform = 'myntra' AND brand_key = 'roadster' AND colour_key = 'blue'
                  AND price_minor BETWEEN 50000 AND 200000 AND rating BETWEEN 4 AND 5
            ORDER BY price_minor, id LIMIT 10
        """)
        self.assertTrue(expected)
        result = search(DB, platform="myntra", brand="Roadster", colour="BLUE",
                        min_price="500.00", max_price="2000", min_rating=4, max_rating=5,
                        sort="price-asc", limit=10)
        self.assertEqual([(row["id"],) for row in result], expected)

    def test_exact_id_name_category_and_fts(self):
        result = search(DB, product_id="SRTEH2FF9KEDEFGF", platform="flipkart",
                        name="CYCLING SHORTS", category="Shorts", keywords="cotton lycra",
                        sort="relevance")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["price_field"], "discounted_price")
        self.assertIn("flipkart.com", result[0]["product_url"])
        self.assertEqual(search(DB, platform="myntra", product_id="SRTEH2FF9KEDEFGF"), [])

    def test_retail_price_filter_and_sort(self):
        result = search(DB, platform="flipkart", price_field="retail",
                        min_price="35", max_price="35", sort="price-asc")
        self.assertTrue(result)
        self.assertTrue(all(row["retail_price_minor"] == 3500 for row in result))
        self.assertEqual(search(DB, platform="myntra", price_field="retail", min_price=0), [])
        result = search(DB, platform="flipkart", price_field="retail", sort="price-desc", limit=5)
        expected = self.query("SELECT id FROM products WHERE platform='flipkart' AND retail_price_minor IS NOT NULL ORDER BY retail_price_minor DESC, id LIMIT 5")
        self.assertEqual([(row["id"],) for row in result], expected)

    def test_myntra_inferred_category_and_missing_rating(self):
        results = search(DB, platform="myntra", category="Kurtas", product_id="17048614")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["category_basis"], "inferred_from_title")
        self.assertEqual(results[0]["price_field"], "price")
        unrated = self.query(
            "SELECT source_id FROM products WHERE platform = 'flipkart' AND rating IS NULL LIMIT 1"
        )[0][0]
        self.assertEqual(search(DB, platform="flipkart", product_id=unrated, min_rating=0), [])

    def test_query_inputs_cannot_change_sql_and_invalid_bounds_fail(self):
        self.assertEqual(search(DB, brand="' OR 1=1 --"), [])
        self.assertEqual(search(DB, keywords='") OR no_such_product *'),
                         search(DB, keywords="or no such product"))
        with self.assertRaises(ValueError):
            search(DB, min_price="2", max_price="1")
        with self.assertRaises(ValueError):
            search(DB, min_rating="NaN")
        with self.assertRaises(ValueError):
            search(DB, sort="id; DROP TABLE products")


if __name__ == "__main__":
    unittest.main()
