import unittest
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from intellimarket_rag.hybrid import HybridSearch, RetrievalConfig, reciprocal_rank_fusion
from intellimarket_rag.matching import assess, audit_identity, compare
from intellimarket_rag.query import Bound, Query, QueryError, parse_query
from intellimarket_rag.semantic import open_catalog


ROOT = Path(__file__).resolve().parents[1]


class QueryTests(unittest.TestCase):
    def test_composed_filters_and_inclusive_boundaries(self):
        query = parse_query("denim jackets on Myntra under 1,500; rating>=4; rating-count>20; colour:Blue")
        self.assertEqual(query.terms, "denim jackets")
        self.assertEqual(query.platform, "myntra")
        self.assertEqual(query.price_max, Bound(Decimal(1500), False))
        self.assertEqual(query.rating_min, Bound(Decimal(4)))
        self.assertEqual(query.count_min, Bound(Decimal(20), False))
        self.assertEqual(query.colour, "Blue")

    def test_ambiguous_and_contradictory_queries_are_rejected(self):
        for text in (
            "watches on Flipkart or Myntra", "compare denim jackets", "dress; maxprice:50",
            "price>10; price<=10", "bags under 4 cm", "shirts only red", "jeans; id:17048614",
            "rating-count>=1.5", "price<1.001", "jeans; platform:myntra; platform:flipkart",
            "tops with minimum rating 4", "shirts with 300 reviews", "bags on Amazon",
        ):
            with self.subTest(text=text), self.assertRaises(QueryError):
                parse_query(text)

    def test_rank_fusion_counts_each_product_once_per_method(self):
        scores = reciprocal_rank_fusion([[1, 1, 2], [2, 3]], k=10)
        self.assertAlmostEqual(scores[1], 1 / 11)
        self.assertAlmostEqual(scores[2], 1 / 11 + 1 / 12)
        self.assertEqual(max(scores, key=scores.get), 2)


class RetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = HybridSearch(ROOT, device="cpu")

    def test_pure_structured_without_model_and_parameter_binding(self):
        structured = HybridSearch(ROOT)
        row = structured.search(parse_query("platform:myntra; id:17048614.0"))[0]
        self.assertEqual(row["product"]["source_id"], "17048614")
        self.assertEqual(row["source"]["file"], "myntra.csv")
        self.assertTrue(row["source"]["records"])
        self.assertEqual(structured.search(Query(brand="' OR 1=1 --")), [])
        self.assertIsNone(structured._semantic)

    def test_explicit_name_filters_exact_name_only(self):
        title = "Alisha Solid Women's Cycling Shorts"
        rows = self.service.search(parse_query(f"name:{title}; platform:flipkart"))
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row["product"]["name"] == title for row in rows))
        tiny = RetrievalConfig(keyword_pool=1, semantic_pool=1)
        rows = self.service.search(Query(terms=title, platform="flipkart"), top_k=1, config=tiny)
        self.assertEqual(rows[0]["product"]["name"], title)

    def test_real_price_boundaries_and_empty_result(self):
        base = "id:BMBEHPAGGDSSYMUZ; platform:flipkart; "
        for constraint, hits in (("price=35", 1), ("price>=35", 1), ("price>35", 0),
                                 ("price<35", 0), ("price<=35", 1)):
            self.assertEqual(len(self.service.search(parse_query(base + constraint))), hits)

    def test_eligible_candidate_found_even_with_small_pool(self):
        query = parse_query("cotton lycra shorts; platform:flipkart; price=379; brand:Alisha")
        config = RetrievalConfig(keyword_pool=2, semantic_pool=2)
        for mode in ("fts", "semantic", "hybrid", "rerank"):
            with self.subTest(mode=mode):
                rows = self.service.search(query, mode=mode, top_k=2, config=config)
                self.assertTrue(rows)
                self.assertEqual(len({row["product"]["id"] for row in rows}), len(rows))
                self.assertTrue(all(row["product"]["price_minor"] == 37900
                                    and row["product"]["brand"] == "Alisha"
                                    and row["product"]["platform"] == "flipkart" for row in rows))

    def test_empty_candidates_skip_dense_and_missing_values_do_not_qualify(self):
        structured = HybridSearch(ROOT)
        self.assertEqual(structured.search(parse_query("cycling shorts; brand:zzzz-empty-zzzz")), [])
        self.assertIsNone(structured._semantic)
        self.assertEqual(structured.search(parse_query("platform:flipkart; rating-count>=0")), [])

    def test_structured_sort_and_count_against_independent_sql(self):
        query = parse_query("platform:myntra; brand:roadster; rating-count>10; price>500; sort:price-desc")
        with closing(open_catalog(self.service.catalog)) as connection:
            expected = [row[0] for row in connection.execute("""
                SELECT id FROM products WHERE platform='myntra' AND brand_key='roadster'
                AND rating_count>10 AND price_minor>50000 ORDER BY price_minor DESC,id LIMIT 10
            """)]
        self.assertTrue(expected)
        self.assertEqual([row["product"]["id"] for row in self.service.search(query)], expected)

    def test_conflicting_variants_do_not_establish_identity(self):
        with closing(open_catalog(self.service.catalog)) as connection:
            left = connection.execute("SELECT * FROM products WHERE source_id='TROEGNQDQNGN99PJ'").fetchone()
            right = connection.execute("SELECT * FROM products WHERE source_id='18395076'").fetchone()
        evidence = assess(left, right, similarity=0.99)
        self.assertTrue(evidence["same_brand"])
        self.assertIn("colour", evidence["variant_conflicts"])
        self.assertNotEqual(evidence["status"], "identical")

    def test_comparison_preserves_source_and_returns_alternatives(self):
        output = compare(self.service, parse_query("compare; platform:myntra; id:17685166"), top_k=3)
        self.assertEqual(output["anchor"]["product"]["price_field"], "price")
        self.assertEqual(output["status"], "similar")
        self.assertIsNone(output["reliable_match"])
        self.assertTrue(output["candidates"])
        self.assertTrue(all(row["product"]["platform"] == "flipkart" and row["source"]["records"]
                            and row["product"]["price_field"] == "discounted_price"
                            for row in output["candidates"]))
        self.assertIsNone(compare(self.service, Query(platform="myntra", product_id="0",
                                                       comparison=True))["anchor"])

    def test_identity_audit_on_real_catalog(self):
        self.assertEqual(audit_identity(self.service.catalog)["rule_supported_identical_pairs"], [])
