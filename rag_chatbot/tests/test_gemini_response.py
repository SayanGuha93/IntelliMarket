import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from intellimarket_rag.chat import Chatbot, Router
from intellimarket_rag.evidence import PLAN_SCHEMA, PlanValidationError, validate_plan
from intellimarket_rag.providers import Gemini, Provider, ProviderError, ProviderReply, Settings


ROOT = Path(__file__).resolve().parents[1]
SEARCH = "cotton lycra cycling shorts; platform:flipkart; price<1500"


class ScriptedReply(Provider):
    """Synthetic SDK replies over real catalog retrieval, with zero network calls."""

    def __init__(self, *responses):
        super().__init__(Settings(provider="gemini", retries=0))
        self.responses = iter(responses)
        self.payloads = []

    def request(self, instruction, payload, schema):
        request = json.loads(payload)
        self.payloads.append(request)
        response = next(self.responses)
        return response(request) if callable(response) else response


def valid_reply(payload):
    item = payload["evidence"][0]
    data = {"selections": [{"evidence_id": item["evidence_id"], "fields": []}]}
    return ProviderReply(json.dumps(data), 40, 12, "STOP", thought_tokens=21)


class GeminiResponseTests(unittest.TestCase):
    def test_broad_filter_keeps_exact_ranked_products_and_reuses_projection(self):
        bot = Chatbot(ROOT, router=Router("hybrid"))
        query = "Find women's cotton kurtas under 1500"
        optimized = bot.respond(bot.new_session(), query)
        self.assertIn("broad_filter_projection", optimized.retrieval_initialization)
        warm = bot.respond(bot.new_session(), query)
        self.assertEqual(warm.retrieval_initialization, {})
        with patch("intellimarket_rag.semantic.BROAD_FILTER_SIZE", 1_000_000):
            reference = bot.respond(bot.new_session(), query)
        expected = [item["evidence_id"] for item in reference.evidence]
        self.assertEqual(len(expected), 5)
        for turn in (optimized, warm):
            self.assertEqual([item["evidence_id"] for item in turn.evidence], expected)
            self.assertTrue(all(item["facts"][("price" if item["platform"] == "myntra"
                                              else "discounted_price")] < 150000
                                for item in turn.evidence))

    def test_sdk_candidate_extracts_visible_json_and_passes_low_thinking(self):
        from google.genai import types

        client = Mock()
        client.models.generate_content.return_value = types.GenerateContentResponse(
            candidates=[types.Candidate(
                finish_reason="STOP", content=types.Content(parts=[
                    types.Part(text="internal-thought-sentinel", thought=True),
                    types.Part(text='{"selections":'),
                    types.Part(text='[{"evidence_id":"flipkart:abc","fields":[]}]}'),
                ]),
            )],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=44, candidates_token_count=18, thoughts_token_count=12,
            ),
        )
        provider = object.__new__(Gemini)
        provider.settings = Settings(provider="gemini", model="gemini-3.8-flash", retries=0)
        provider.client, provider.types = client, types
        completion = provider.complete("Return selectors", {}, PLAN_SCHEMA)
        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.thinking_config.thinking_level.value, "LOW")
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(completion.details["thought_tokens"], 12)
        self.assertEqual(completion.details["finish_reason"], "STOP")
        self.assertNotIn("internal-thought-sentinel", json.dumps(completion.data))

    def test_wire_failures_have_safe_distinct_categories(self):
        for reply, reason, category in (
            (ProviderReply(None, 40, 0, "STOP"), "invalid_response", "empty_output"),
            (ProviderReply('{"selections":[', 40, 7, "STOP"), "invalid_response", "malformed_json"),
            (ProviderReply("[]", 40, 2, "STOP"), "invalid_response", "wrong_top_level_type"),
            (ProviderReply('{"x":1,"x":2}', 40, 7, "STOP"), "invalid_response", "duplicate_json_key"),
            (ProviderReply('{"selections":[', 40, 7, "MAX_TOKENS"), "response_truncated", "output_token_limit"),
            (ProviderReply(None, 40, 0, "SAFETY"), "response_blocked", "provider_stopped"),
        ):
            with self.subTest(category=category):
                provider = ScriptedReply(reply)
                with self.assertRaises(ProviderError) as caught:
                    provider.complete("Return selectors", {}, PLAN_SCHEMA)
                error = caught.exception
                self.assertEqual((error.reason, error.details["category"]), (reason, category))
                self.assertEqual(error.input_tokens, 40)
                self.assertTrue(error.responded)
                self.assertNotIn(reply.text or "absent", str(error))

    def test_fenced_json_still_uses_strict_evidence_validation(self):
        provider = ScriptedReply(ProviderReply('```json\n{"selections":[{"evidence_id":"invalid-secret","fields":[]}]}\n```',
                                               40, 7, "STOP"))
        result = provider.complete("Return selectors", {}, PLAN_SCHEMA)
        with self.assertRaises(PlanValidationError) as caught:
            validate_plan(result.data, {"real:evidence": set()})
        self.assertEqual(caught.exception.details, {"category": "unknown_evidence_id",
                                                    "path": "$.selections[0].evidence_id"})
        self.assertNotIn("invalid-secret", str(caught.exception))

    def test_missing_and_ineligible_fields_are_rejected(self):
        cases = (
            ({}, "missing_required", "$.selections"),
            ({"selections": [{"evidence_id": "real:evidence"}]}, "missing_required", "$.selections[0].fields"),
            ({"selections": [{"evidence_id": "real:evidence", "fields": ["price"]}]},
             "undisclosed_field", "$.selections[0].fields[0]"),
        )
        for data, category, path in cases:
            with self.subTest(path=path), self.assertRaises(PlanValidationError) as caught:
                validate_plan(data, {"real:evidence": {"brand"}})
            self.assertEqual(caught.exception.details, {"category": category, "path": path})

    def test_one_call_path_preserves_constraints_and_session_references(self):
        provider = ScriptedReply(valid_reply)
        bot = Chatbot(ROOT, provider=provider, router=Router("fts"), intent_assistance=False, top_k=2)
        session = bot.new_session()
        turn = bot.respond(session, SEARCH)
        self.assertEqual(len(provider.payloads), 1)
        self.assertEqual(turn.diagnostics()["actual_provider"], "gemini")
        self.assertEqual(turn.intent_stage.status, "not_attempted")
        self.assertTrue(all(row["facts"]["discounted_price"] < 150000 for row in turn.evidence))
        self.assertTrue(all("description" not in item and "discounted_price" not in item["facts"]
                            for item in provider.payloads[0]["evidence"]))
        follow = bot.respond(session, "Tell me more about the second product.")
        self.assertEqual(follow.evidence[0]["id"], turn.evidence[1]["id"])
        self.assertEqual(len(provider.payloads), 1)

    def test_truncated_output_gets_one_smaller_correction(self):
        provider = ScriptedReply(ProviderReply('{"selections":', 90, 7, "MAX_TOKENS", thought_tokens=80),
                                 valid_reply)
        bot = Chatbot(ROOT, provider=provider, router=Router("fts"), intent_assistance=False, top_k=3)
        turn = bot.respond(bot.new_session(), SEARCH)
        debug = turn.diagnostics()
        self.assertEqual(debug["actual_provider"], "gemini")
        self.assertFalse(debug["fallback_triggered"])
        self.assertEqual(debug["generation_attempts"][0]["category"], "output_token_limit")
        self.assertEqual([len(payload["evidence"]) for payload in provider.payloads], [3, 1])
        self.assertEqual((debug["input_tokens"], debug["output_tokens"]), (130, 19))
        self.assertEqual(len(turn.evidence), 3)

    def test_incomplete_json_twice_falls_back_and_unknown_id_never_retries(self):
        broken = ProviderReply('{"selections":[', 40, 7, "STOP")
        invalid = ProviderReply('{"selections":[{"evidence_id":"secret-sentinel","fields":[]}]}', 40, 7, "STOP")
        for provider, expected, attempts in (
            (ScriptedReply(broken, broken), "malformed_json", 2),
            (ScriptedReply(invalid), "unknown_evidence_id", 1),
        ):
            bot = Chatbot(ROOT, provider=provider, router=Router("fts"), intent_assistance=False)
            turn = bot.respond(bot.new_session(), SEARCH)
            debug = turn.diagnostics()
            self.assertEqual(debug["actual_provider"], "fallback")
            self.assertTrue(debug["fallback_triggered"])
            self.assertEqual(debug["generation_attempts"][-1]["category"], expected)
            self.assertEqual(len(provider.payloads), attempts)
            self.assertNotIn("secret-sentinel", turn.answer + json.dumps(debug))


if __name__ == "__main__":
    unittest.main()
