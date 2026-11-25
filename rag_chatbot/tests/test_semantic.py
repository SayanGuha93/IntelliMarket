import json
import re
import unittest
from collections import Counter
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import numpy as np

from intellimarket_rag.documents import chunk_document, product_document
from intellimarket_rag.semantic import (
    CONFIG, DIMENSIONS, QUERY_PROMPT, SemanticSearch, active_index, build_index,
    catalog_identity, open_catalog, validate_index,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "artifacts" / "catalog.sqlite3"


class SemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = SemanticSearch(ROOT, device="cpu")

    def product(self, sql, args=()):
        with closing(open_catalog(CATALOG)) as connection:
            return dict(connection.execute(sql, args).fetchone())

    def test_document_contains_descriptive_facts_not_source_id_or_prices(self):
        product = self.product(
            "SELECT * FROM products WHERE source_id = ?", ("SRTEH2FF9KEDEFGF",)
        )
        title, sections = product_document(product)
        text = "\n".join([title, *sections])
        self.assertIn("Cycling Shorts", title)
        self.assertIn("Fabric: Cotton Lycra", text)
        self.assertNotIn(product["source_id"], text)
        self.assertNotIn(product["product_url"], text)
        self.assertNotRegex(text, r"(?i)\bRs\.?\s*\d")

    def test_uncategorized_myntra_uses_recorded_evidence(self):
        product = self.product("""
            SELECT * FROM products WHERE platform='myntra' AND category_path='[]'
            AND description IS NOT NULL AND attributes <> '{}' LIMIT 1
        """)
        title, sections = product_document(product)
        self.assertTrue(title and sections)
        self.assertTrue(any(section.startswith("Description: ") for section in sections))
        self.assertFalse(any(section.startswith("Category: ") for section in sections))
        self.assertNotIn(product["source_id"], "\n".join(sections))

    def test_conflicting_descriptions_are_not_added_to_the_document(self):
        product = self.product("""
            SELECT * FROM products WHERE platform='myntra'
            AND json_type(conflicts, '$.description') = 'array' LIMIT 1
        """)
        self.assertIsNone(product["description"])
        self.assertGreaterEqual(len(json.loads(product["conflicts"])["description"]), 2)
        _, sections = product_document(product)
        self.assertFalse(any(section.startswith("Description: ") for section in sections))

    def test_long_real_document_obeys_model_token_budget(self):
        product = self.product(
            "SELECT * FROM products ORDER BY length(description) DESC LIMIT 1"
        )
        tokenizer = self.service.model.tokenizer
        title, sections = product_document(product)
        budget = CONFIG["chunk_tokens"]
        chunks = chunk_document(tokenizer, title, sections, budget)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(len(chunks), len(set(chunks)))
        for chunk in chunks:
            self.assertLessEqual(len(tokenizer.encode(chunk, add_special_tokens=False)), budget)
            self.assertTrue(chunk.startswith("Product: "))

    def test_actual_model_output_has_384_normalized_dimensions(self):
        vector = self.service.model.encode(
            ["Clothing suitable for cycling"], prompt=QUERY_PROMPT, normalize_embeddings=True,
        )[0]
        self.assertEqual(vector.shape, (DIMENSIONS,))
        self.assertTrue(np.isfinite(vector).all())
        self.assertAlmostEqual(float(np.linalg.norm(vector)), 1.0, places=5)
        stored = self.service.table.search().select(["vector"]).limit(5).to_list()
        self.assertEqual(len(stored), 5)
        for row in stored:
            self.assertEqual(len(row["vector"]), DIMENSIONS)
            self.assertAlmostEqual(float(np.linalg.norm(row["vector"])), 1.0, places=5)

    def test_persistence_and_all_chunk_mappings(self):
        path, manifest = active_index(ROOT)
        self.assertTrue(all(manifest[field] == value for field, value in catalog_identity(ROOT).items()))
        table = validate_index(path, manifest)
        chunks = table.search().select(
            ["chunk_id", "product_id", "platform", "source_id", "source_records"]
        ).limit(manifest["vector_count"]).to_list()
        with closing(open_catalog(CATALOG)) as connection:
            expected = {}
            for row in connection.execute("""
                SELECT p.id, p.platform, p.source_id, r.record_number
                FROM products p JOIN source_records r ON r.product_id=p.id
                WHERE r.status='accepted' ORDER BY p.id, r.record_number
            """):
                expected.setdefault(row["id"], (row["platform"], row["source_id"], []))[2].append(
                    row["record_number"]
                )
        self.assertEqual(len(chunks), manifest["vector_count"])
        self.assertEqual(len({row["chunk_id"] for row in chunks}), len(chunks))
        self.assertEqual(set(row["product_id"] for row in chunks), set(expected))
        count = Counter(row["product_id"] for row in chunks)
        self.assertGreater(max(count.values()), 1)
        for row in chunks:
            self.assertEqual((row["platform"], row["source_id"], row["source_records"]),
                             expected[row["product_id"]])

    def test_exact_semantic_search_dedupes_and_hydrates_facts(self):
        results = self.service.search("Cycling shorts for women", platform="flipkart", top_k=10)
        self.assertEqual(len(results), 10)
        self.assertEqual(len({row["product"]["id"] for row in results}), 10)
        self.assertTrue(all(row["product"]["platform"] == "flipkart" for row in results))
        self.assertTrue(any(re.search("cycling shorts", row["product"]["name"], re.I) for row in results))
        scores = [row["similarity"] for row in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for row in results:
            product = row["product"]
            self.assertEqual(product, self.product("SELECT * FROM products WHERE id = ?", (product["id"],)))
            self.assertEqual(row["source"]["file"], "flipkart.csv")
            self.assertTrue(row["source"]["records"])

    def test_myntra_platform_restriction(self):
        results = self.service.search("Denim jacket", platform="myntra", top_k=5)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(row["product"]["platform"] == "myntra" for row in results))
        with self.assertRaises(ValueError):
            self.service.search("Denim jacket", platform="other")

    def test_unchanged_build_reuses_active_index(self):
        _, before = active_index(ROOT)
        result = build_index(ROOT)
        self.assertTrue(result["reused"])
        self.assertEqual(result["build_id"], before["build_id"])

    def test_service_rejects_catalog_fingerprint_mismatch(self):
        changed = {**catalog_identity(ROOT), "catalog_sha256": "different"}
        with patch("intellimarket_rag.semantic.catalog_identity", return_value=changed):
            with self.assertRaisesRegex(ValueError, "does not match the catalog"):
                SemanticSearch(ROOT, device="cpu")

    def test_evaluation_label_set_uses_actual_catalog_items(self):
        lines = (ROOT / "evaluation" / "semantic_queries.jsonl").read_text(encoding="utf-8").splitlines()
        cases = [json.loads(line) for line in lines]
        self.assertGreaterEqual(len({case["query"] for case in cases}), 30)
        with closing(open_catalog(CATALOG)) as connection:
            for case in cases:
                for item in case["relevant"]:
                    platform, source_id = item.split(":", 1)
                    self.assertIsNotNone(connection.execute(
                        "SELECT 1 FROM products WHERE platform = ? AND source_id = ?", (platform, source_id)
                    ).fetchone())
