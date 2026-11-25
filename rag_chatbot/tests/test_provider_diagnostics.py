import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from intellimarket_rag.chat import Chatbot, Router
from intellimarket_rag.chat_cli import interactive
from intellimarket_rag.evidence import PLAN_SCHEMA
from intellimarket_rag.providers import Completion, ProviderError, Settings


ROOT = Path(__file__).resolve().parents[1]
SEARCH = "cotton lycra cycling shorts; platform:flipkart"
LOOKUP = "platform:myntra; id:17685166"


class GeminiStub:
    settings = Settings(provider="gemini", key="test-secret-sentinel")

    def __init__(self, failure=None):
        self.failure = failure

    def complete(self, instruction, payload, schema):
        if schema is PLAN_SCHEMA:
            if self.failure == "rate_limited":
                raise ProviderError("secret-from-provider", reason="rate_limited")
            item = payload["evidence"][0]
            data = {"selections": [{"evidence_id": item["evidence_id"], "fields": []}]}
            if self.failure == "rejected":
                data["invented"] = "secret-from-provider"
        else:
            if self.failure == "both":
                raise ProviderError("secret-from-provider", reason="timeout")
            data = {**payload["deterministic"], "clarification": False, "preference": "fts"}
        if self.failure == "both":
            raise ProviderError("secret-from-provider", reason="timeout")
        return Completion(data, 11, 3, 0.2)


class ProviderDiagnosticTests(unittest.TestCase):
    def test_valid_gemini_then_contextual_turn_and_reset(self):
        bot = Chatbot(ROOT, provider=GeminiStub(), router=Router("fts"), top_k=2)
        session = bot.new_session()
        turn = bot.respond(session, SEARCH)
        debug = turn.diagnostics()
        self.assertEqual(debug["requested_provider"], "gemini")
        self.assertEqual(debug["actual_provider"], "gemini")
        self.assertTrue(debug["gemini_inference_succeeded"])
        self.assertFalse(debug["fallback_triggered"])
        self.assertEqual((debug["input_tokens"], debug["output_tokens"]), (22, 6))
        self.assertEqual(debug["retrieved_product_count"], 2)
        self.assertGreater(debug["timing_ms"]["llm"], 0)
        self.assertGreaterEqual(debug["timing_ms"]["end_to_end"], debug["timing_ms"]["llm"])
        follow = bot.respond(session, "Tell me more about the second product.")
        debug = follow.diagnostics()
        self.assertEqual(follow.evidence[0]["id"], turn.evidence[1]["id"])
        self.assertEqual(debug["strategy"], "session_lookup")
        self.assertEqual(debug["actual_provider"], "fallback")
        self.assertIsNone(debug["gemini_inference_succeeded"])
        self.assertFalse(debug["fallback_triggered"])
        self.assertEqual(debug["deterministic_reason"], "no_model_needed_for_route")
        self.assertEqual(debug["timing_ms"]["llm"], 0)
        self.assertIsNone(debug["input_tokens"])
        bot.respond(session, "/reset")
        self.assertEqual(bot.respond(session, "Does it have pockets?").action, "clarify")

    def test_partial_success_and_validation_rejection_remain_distinct(self):
        for behavior, reason, status in (
            ("rate_limited", "rate_limited", "failed"),
            ("rejected", "validation_rejected", "rejected"),
        ):
            with self.subTest(behavior=behavior):
                bot = Chatbot(ROOT, provider=GeminiStub(behavior), router=Router("fts"))
                debug = bot.respond(bot.new_session(), SEARCH).diagnostics()
                self.assertTrue(debug["gemini_inference_succeeded"])
                self.assertEqual(debug["actual_provider"], "fallback")
                self.assertEqual(debug["intent_provider"], "gemini")
                self.assertEqual(debug["provider_stages"]["generation"]["status"], status)
                self.assertTrue(debug["fallback_triggered"])
                self.assertEqual(debug["fallback_reasons"], {"generation": reason})
                self.assertNotIn("secret", json.dumps(debug))

    def test_both_failed_does_not_report_gemini_success(self):
        bot = Chatbot(ROOT, provider=GeminiStub("both"), router=Router("fts"))
        debug = bot.respond(bot.new_session(), SEARCH).diagnostics()
        self.assertIs(debug["gemini_inference_succeeded"], False)
        self.assertEqual(debug["fallback_reasons"], {"intent": "timeout", "generation": "timeout"})
        self.assertIsNone(debug["output_tokens"])

    def test_cli_debug_is_optional_and_missing_key_has_safe_reason(self):
        for debug in (True, False):
            output, errors = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {}, clear=True), patch("builtins.input", side_effect=[LOOKUP, "/exit"]):
                with redirect_stdout(output), redirect_stderr(errors):
                    interactive(ROOT, debug=debug, provider="gemini", model="configured-model")
            events = [json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")]
            self.assertIn("missing_api_key", errors.getvalue())
            if debug:
                startup, turn = events
                self.assertEqual(startup["requested_provider"], "gemini")
                self.assertEqual(turn["actual_provider"], "fallback")
                self.assertTrue(turn["fallback_triggered"])
                self.assertEqual(turn["fallback_reasons"], {"configuration": "missing_api_key"})
                self.assertIsNone(turn["gemini_inference_succeeded"])
            else:
                self.assertEqual(events, [])
