import asyncio
import unittest
from contextlib import asynccontextmanager, closing
from pathlib import Path
from threading import Event
from uuid import uuid4

import httpx

from intellimarket_rag.api import ApiSettings, create_app
from intellimarket_rag.chat import Chatbot
from intellimarket_rag.paths import open_catalog
from intellimarket_rag.providers import Completion, ProviderError, Settings


ROOT = Path(__file__).resolve().parents[1]
DENIM = "platform:myntra; id:17685166"
ALISHA = "platform:flipkart; id:SRTEH2FF9KEDEFGF"
COTTON = "Find women's cotton kurtas under 1500"


@asynccontextmanager
async def local_api(*, settings=ApiSettings(), bot=None):
    app = create_app(settings, bot_factory=lambda: bot or Chatbot(ROOT))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://local.test") as client:
            yield app, client


async def session(client):
    response = await client.post("/api/session")
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


async def send(client, identifier, message):
    return await client.post("/api/chat", json={"session_id": identifier, "message": message})


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_and_openapi_examples(self):
        async with local_api() as (_, client):
            result = await client.get("/api/health")
            self.assertEqual(result.json(), {"status": "ok", "catalog_ready": True,
                                             "dense_ready": False, "warmup_enabled": False})
            self.assertEqual(result.headers["cache-control"], "no-store")
            self.assertEqual((await client.get("/docs")).status_code, 200)
            schema = (await client.get("/openapi.json")).json()
            self.assertEqual(set(schema["paths"]), {"/api/health", "/api/session",
                                                    "/api/session/{session_id}", "/api/chat"})
            example = schema["paths"]["/api/chat"]["post"]["responses"]["200"]["content"]["application/json"]["example"]
            self.assertEqual(example["products"][0]["product_id"], "17685166")

    async def test_create_get_delete_and_capacity(self):
        async with local_api(settings=ApiSettings(max_sessions=1)) as (_, client):
            identifier = await session(client)
            state = await client.get(f"/api/session/{identifier}")
            self.assertEqual(state.json()["recent_messages"], [])
            self.assertEqual((await client.post("/api/session")).status_code, 503)
            deleted = await client.delete(f"/api/session/{identifier}")
            self.assertEqual((deleted.status_code, deleted.content), (204, b""))
            self.assertEqual((await client.get(f"/api/session/{identifier}")).status_code, 404)
            self.assertEqual((await send(client, identifier, DENIM)).status_code, 404)
            self.assertNotEqual(await session(client), identifier)

    async def test_expiry_and_successful_turn_refresh(self):
        async with local_api(settings=ApiSettings(ttl_seconds=10)) as (app, client):
            now = [100.]
            app.state.sessions._clock = lambda: now[0]
            identifier = await session(client)
            now[0] += 8
            self.assertEqual((await send(client, identifier, DENIM)).status_code, 200)
            now[0] += 5
            self.assertEqual((await client.get(f"/api/session/{identifier}")).status_code, 200)
            now[0] += 6
            self.assertEqual((await client.get(f"/api/session/{identifier}")).status_code, 404)

    async def test_session_isolation_and_contextual_followups(self):
        async with local_api() as (_, client):
            first, second = await session(client), await session(client)
            self.assertEqual((await send(client, first, DENIM)).status_code, 200)
            missing = (await send(client, second, "Does it have pockets?")).json()
            self.assertEqual(missing["action"], "clarify")
            self.assertEqual(missing["products"], [])
            detail = (await send(client, first, "Does it have pockets?")).json()
            self.assertEqual(detail["products"][0]["product_id"], "17685166")
            self.assertIn("Number of pockets: 2", detail["answer"])
            one_state = (await client.get(f"/api/session/{first}")).json()
            two_state = (await client.get(f"/api/session/{second}")).json()
            self.assertEqual((len(one_state["recent_messages"]), len(two_state["recent_messages"])), (4, 2))
            await send(client, first, "/reset")
            self.assertEqual((await client.get(f"/api/session/{first}")).json()["recent_messages"], [])

    async def test_filters_hold_across_platform_and_colour_changes(self):
        async with local_api() as (_, client):
            identifier = await session(client)
            for index, message in enumerate((COTTON, "What about Myntra?", "Only show black ones.")):
                response = await send(client, identifier, message)
                self.assertEqual(response.status_code, 200, response.text)
                products = response.json()["products"]
                self.assertTrue(products)
                for product in products:
                    self.assertNotEqual(product["product_id"], "KRTEJ8EWCZNMX9YM")
                    self.assertTrue(any(product["attributes"].get(field) == ["Cotton"] for field in (
                        "fabric", "kurta fabric", "top fabric",
                    )))
                    recorded = next(price for price in product["prices"] if price["kind"] != "retail_price")
                    self.assertLess(recorded["amount_minor"], 150000)
                    self.assertIsNone(recorded["currency"])
                    if index:
                        self.assertEqual(product["marketplace"], "myntra")
                    if index == 2:
                        self.assertEqual(product["colour"].lower(), "black")

    async def test_catalog_citations_ratings_and_presentation(self):
        async with local_api() as (_, client):
            identifier = await session(client)
            first = (await send(client, identifier, ALISHA)).json()
            product = first["products"][0]
            self.assertIn("historical", first["historical_data_disclaimer"])
            self.assertTrue(product["product_url"].startswith("http://www.flipkart.com/"))
            with closing(open_catalog(ROOT / "artifacts" / "catalog.sqlite3")) as connection:
                expected = [tuple(row) for row in connection.execute("""
                    SELECT r.record_number, r.source_record_id,
                           json_extract(r.normalized_json, '$.observed_at'),
                           json_extract(r.normalized_json, '$.product_url')
                    FROM products p JOIN source_records r ON r.product_id=p.id
                    WHERE p.platform='flipkart' AND p.source_id='SRTEH2FF9KEDEFGF'
                    AND r.status='accepted' ORDER BY r.record_number
                """)]
                raw_rating = connection.execute(
                    "SELECT rating FROM products WHERE platform='myntra' AND source_id='11489658'"
                ).fetchone()[0]
            self.assertEqual([
                (row["record_number"], row["source_record_id"], row["observed_at"], row["product_url"])
                for row in product["citations"]
            ], expected)
            self.assertTrue(all(row["source_file"] == "flipkart.csv" for row in product["citations"]))
            rated = (await send(client, identifier, "platform:myntra; id:11489658")).json()
            self.assertEqual(rated["products"][0]["rating"], {"raw": raw_rating, "display": f"{raw_rating:.2f}"})
            self.assertIn(f"Recorded rating: {raw_rating:.2f}", rated["answer"])
            denim = (await send(client, identifier, DENIM)).json()
            self.assertNotIn("Garment Measurements in", denim["answer"])
            self.assertNotIn("body or garment size", denim["products"][0]["attributes"])

    async def test_wire_json_is_utf8(self):
        async with local_api() as (_, client):
            response = await send(client, await session(client), ALISHA)
            self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")
            self.assertIn(b"\xc2\xb7", response.content)
            self.assertIn(b"2015\xe2\x80\x932016", response.content)
            self.assertIn("·", response.json()["answer"])

    async def test_opt_in_server_audit_distinguishes_gemini_and_local_answers(self):
        class ProviderStub:
            settings = Settings(provider="gemini", key="key-sentinel")

            def complete(self, _instruction, payload, _schema):
                evidence = payload["evidence"][0]
                return Completion({"selections": [
                    {"evidence_id": evidence["evidence_id"], "fields": []},
                ]}, None, None, 0)

        bot = Chatbot(ROOT, provider=ProviderStub(), intent_assistance=False)
        async with local_api(settings=ApiSettings(provider_audit=True), bot=bot) as (_, client):
            identifier = await session(client)
            with self.assertLogs("uvicorn.error", level="INFO") as logs:
                result = await send(client, identifier, COTTON)
                detail = await send(client, identifier, "Tell me more about the second product.")
            self.assertEqual((result.status_code, detail.status_code), (200, 200))
            self.assertIn("requested=gemini actual=gemini generation=succeeded fallback=no", logs.output[0])
            self.assertIn("requested=gemini actual=fallback generation=not_attempted fallback=no", logs.output[1])
            for value in (identifier, "key-sentinel", COTTON):
                self.assertNotIn(value, "\n".join(logs.output))
            self.assertNotIn("generation=", result.text)

    async def test_invalid_requests_and_origin_allowlist(self):
        origins = ("http://localhost:5173",)
        async with local_api(settings=ApiSettings(origins=origins)) as (_, client):
            identifier = await session(client)
            for payload in (
                {"session_id": identifier, "message": "   "}, {"session_id": "bad", "message": "search"},
                {"session_id": identifier, "message": "a" * 1501},
                {"session_id": identifier, "message": "query", "internal": "secret-sentinel"},
            ):
                result = await client.post("/api/chat", json=payload)
                self.assertEqual(result.status_code, 422)
                self.assertNotIn("secret-sentinel", result.text)
            self.assertEqual((await client.post("/api/chat", content=b"x" * 20000)).status_code, 413)
            self.assertEqual((await send(client, str(uuid4()), DENIM)).status_code, 404)
            self.assertEqual((await client.get("/api/session/not-a-uuid")).status_code, 422)
            for origin, code in ((origins[0], 200), ("https://example.com", 400)):
                response = await client.options("/api/chat", headers={
                    "Origin": origin, "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                })
                self.assertEqual(response.status_code, code)
                self.assertEqual(response.headers.get("access-control-allow-origin"), origin if code == 200 else None)

    async def test_provider_failure_preserves_safe_fallback(self):
        class FailingProvider:
            settings = Settings(provider="gemini")

            def complete(self, *_args):
                raise ProviderError("provider-secret-sentinel", reason="rate_limited")

        bot = Chatbot(ROOT, provider=FailingProvider(), intent_assistance=False)
        async with local_api(bot=bot) as (_, client):
            result = await send(client, await session(client), COTTON)
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json()["products"])
            for forbidden in ("provider-secret-sentinel", "rate_limited", "provider_stages", "api_key"):
                self.assertNotIn(forbidden, result.text)

    async def test_concurrent_turns_and_delete_while_running(self):
        bot = Chatbot(ROOT)
        original = bot.respond
        started, release = Event(), Event()

        def blocking(snapshot, message):
            if message == DENIM:
                started.set()
                if not release.wait(5):
                    raise RuntimeError("Test gate timed out.")
            return original(snapshot, message)

        bot.respond = blocking
        async with local_api(bot=bot, settings=ApiSettings(max_in_flight=2)) as (_, client):
            first, second = await session(client), await session(client)
            pending = asyncio.create_task(send(client, first, DENIM))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 3))
                self.assertEqual((await send(client, first, ALISHA)).status_code, 409)
                self.assertEqual((await send(client, second, ALISHA)).status_code, 200)
                self.assertTrue((await client.get(f"/api/session/{first}")).json()["busy"])
                self.assertEqual((await client.delete(f"/api/session/{first}")).status_code, 204)
            finally:
                release.set()
            self.assertEqual((await pending).status_code, 404)

    async def test_timeout_keeps_capacity_bounded_and_drops_late_state(self):
        bot = Chatbot(ROOT)
        original = bot.respond
        release = Event()

        def blocking(snapshot, message):
            if message == DENIM:
                if not release.wait(5):
                    raise RuntimeError("Test gate timed out.")
            return original(snapshot, message)

        bot.respond = blocking
        async with local_api(bot=bot, settings=ApiSettings(max_in_flight=1, timeout_seconds=.12)) as (_, client):
            first, second = await session(client), await session(client)
            try:
                self.assertEqual((await send(client, first, DENIM)).status_code, 504)
                self.assertEqual((await send(client, first, ALISHA)).status_code, 409)
                self.assertEqual((await send(client, second, ALISHA)).status_code, 503)
            finally:
                release.set()
            for _ in range(100):
                state = (await client.get(f"/api/session/{first}")).json()
                if not state["busy"]:
                    break
                await asyncio.sleep(.01)
            self.assertFalse(state["busy"])
            self.assertEqual(state["recent_messages"], [])

    async def test_comparison_uses_marketplace_qualified_evidence(self):
        async with local_api() as (_, client):
            identifier = await session(client)
            result = (await send(client, identifier, "compare; platform:myntra; id:17685166")).json()
            comparison = result["comparison"]
            self.assertEqual(comparison["status"], "similar")
            self.assertEqual(comparison["anchor_evidence_id"], "myntra:17685166")
            self.assertIsNone(comparison["identical_match_evidence_id"])
            self.assertIn("flipkart:JCKEGDFGPZZFBJ63", comparison["product_evidence_ids"])


if __name__ == "__main__":
    unittest.main()
