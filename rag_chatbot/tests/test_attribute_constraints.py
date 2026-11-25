import json
import unittest
from pathlib import Path

from intellimarket_rag.chat import Chatbot, Router
from intellimarket_rag.evidence import PLAN_SCHEMA
from intellimarket_rag.hybrid import HybridSearch
from intellimarket_rag.providers import Completion, Settings
from intellimarket_rag.query import QueryError, parse_query


ROOT = Path(__file__).resolve().parents[1]
QUERY = "Find women's cotton kurtas under 1500"
FALSE_MATCH = "KRTEJ8EWCZNMX9YM"
LYCRA = "SRTEH2FF9KEDEFGF"


class AttributeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.search = HybridSearch(ROOT)

    def test_exact_reported_query_enforces_fabric_and_price_in_every_mode(self):
        question = parse_query(QUERY)
        self.assertEqual((question.fabric, question.gender), ("cotton", "women"))
        self.assertFalse(question.price_max.inclusive)
        for mode in ("fts", "semantic", "hybrid", "rerank"):
            with self.subTest(mode=mode):
                rows = self.search.search(question, mode=mode, top_k=5)
                self.assertTrue(rows)
                for row in rows:
                    product = row["product"]
                    self.assertNotEqual(product["source_id"], FALSE_MATCH)
                    self.assertLess(product["price_minor"], 150000)
                    attrs = json.loads(product["attributes"])
                    main_fabric = next(attrs[key] for key in (
                        "fabric", "kurta fabric", "top fabric", "saree fabric", "lehenga fabric",
                    ) if key in attrs)
                    self.assertTrue(all(value.casefold() in {"cotton", "pure cotton", "100% cotton",
                                                            "organic cotton", "cotton jersey"}
                                        for value in main_fabric), main_fabric)

    def test_brand_and_description_cannot_override_primary_fabric(self):
        def lookup(filters):
            return self.search.search(parse_query(f"id:{FALSE_MATCH}; {filters}"))

        rows = lookup("brand:Cotton Fab; fabric:poly crepe")
        self.assertEqual(len(rows), 1)
        self.assertIn("Poly Crepe", rows[0]["product"]["attributes"])
        self.assertEqual(lookup("brand:Cotton Fab; fabric:cotton"), [])

    def test_blends_and_pure_cotton_are_distinct(self):
        def lookup(product_id, fabric):
            return self.search.search(parse_query(f"id:{product_id}; fabric:{fabric}"))

        self.assertEqual(lookup(LYCRA, "cotton"), [])
        self.assertEqual(lookup(LYCRA, "pure cotton"), [])
        self.assertEqual(len(lookup(LYCRA, "cotton blend")), 1)
        self.assertEqual(len(lookup(LYCRA, "cotton lycra")), 1)
        self.assertEqual(lookup(LYCRA, "cotton polyester"), [])
        self.assertEqual(len(lookup("15913410", "100% cotton")), 1)
        self.assertEqual(parse_query("100% cotton kurtas").fabric, "pure cotton")

    def test_components_and_missing_fabric_are_conservative(self):
        self.assertEqual(self.search.search(parse_query("id:17048614; fabric:cotton")), [])
        self.assertTrue(self.search.search(parse_query("id:17048614; bottom-fabric:rayon")))
        self.assertEqual(self.search.search(parse_query("id:BMBEHPAGGDSSYMUZ; fabric:cotton")), [])
        self.assertEqual(parse_query("cotton kurta with rayon palazzos").bottom_fabric, "rayon")

    def test_natural_gender_colour_and_closure(self):
        query = parse_query("black washed crop denim jacket for women with snap buttons; platform:myntra")
        self.assertEqual((query.colour, query.gender, query.closure), ("black", "women", "snap button"))
        rows = self.search.search(query, mode="fts", top_k=5)
        self.assertIn("17685166", [row["product"]["source_id"] for row in rows])
        self.assertEqual(self.search.search(parse_query("id:17685166; gender:men")), [])
        self.assertTrue(self.search.search(parse_query("id:15913410; pattern:floral")))
        self.assertEqual(self.search.search(parse_query("id:KTAEHETWRNSWM4EF; pattern:floral")), [])

    def test_ambiguous_and_unsupported_constraints_ask_for_clarification(self):
        for query in ("cotton or linen kurtas", "non-cotton kurtas", "cotton-free kurtas",
                      "cotton or bamboo kurtas", "bamboo or cotton kurtas",
                      "kurtas not made of cotton", "kurtas without any cotton",
                      "cotton, polyester kurtas", "kurtas made of unknown fibre",
                      "cotton kurtas; fabric:linen", "fabric:cotton' OR 1=1 --"):
            with self.subTest(query=query), self.assertRaises(QueryError):
                parse_query(query)

    def test_follow_up_preserves_fabric_gender_and_price(self):
        bot = Chatbot(ROOT, router=Router("fts"))
        session = bot.new_session()
        bot.respond(session, QUERY)
        switched = bot.respond(session, "What about Myntra?")
        refined = bot.respond(session, "Only show black ones.")
        pure = bot.respond(session, "Only show pure cotton ones.")
        for turn in (switched, refined, pure):
            self.assertEqual(turn.query.gender, "women")
            self.assertEqual(turn.query.platform, "myntra")
            self.assertEqual(str(turn.query.price_max.value), "1500")
        self.assertEqual(refined.query.fabric, "cotton")
        self.assertEqual(refined.query.colour, "black")
        self.assertEqual(pure.query.fabric, "pure cotton")
        self.assertEqual(pure.query.colour, "black")

    def test_gemini_cannot_remove_fabric_or_select_an_ineligible_product(self):
        class UntrustedProvider:
            settings = Settings(provider="gemini")

            def complete(self, _instruction, payload, schema):
                if schema is PLAN_SCHEMA:
                    return Completion({"selections": [
                        {"evidence_id": f"flipkart:{FALSE_MATCH}", "fields": []},
                    ]}, None, None, 0)
                controlled = payload["deterministic"]
                proposal = {**controlled, "clarification": False, "preference": "auto",
                            "query": {**controlled["query"], "fabric": None}}
                return Completion(proposal, None, None, 0)

        bot = Chatbot(ROOT, provider=UntrustedProvider(), router=Router("fts"))
        turn = bot.respond(bot.new_session(), QUERY)
        self.assertEqual(turn.intent_stage.status, "rejected")
        self.assertEqual(turn.generation_stage.details["category"], "unknown_evidence_id")
        self.assertEqual(turn.query.fabric, "cotton")
        self.assertNotIn(FALSE_MATCH, turn.answer)
        self.assertIn("Fabric: Cotton", turn.answer)
