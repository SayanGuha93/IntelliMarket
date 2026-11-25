"""Standalone FastAPI adapter for the existing IntelliMarket RAG chatbot."""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import UUID4

from .api_models import (DISCLAIMER, SESSION_EXAMPLE, ChatRequest, ChatResponse, ErrorResponse,
                         HealthResponse, SessionResponse, project_turn)
from .api_sessions import SessionBusy, SessionCapacity, SessionMissing, SessionStore
from .chat_cli import configured_bot
from .query import parse_query
from .semantic import active_index, catalog_identity


LOCAL_ORIGINS = tuple(f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (3000, 5173))
MAX_BODY_BYTES = 16 * 1024
NOT_FOUND = "Session was not found or has expired."
PROVIDER_AUDIT = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class ApiSettings:
    origins: tuple[str, ...] = LOCAL_ORIGINS
    ttl_seconds: int = 1800
    max_sessions: int = 100
    max_in_flight: int = 4
    timeout_seconds: float = 45
    warmup: bool = False
    provider_audit: bool = False

    def __post_init__(self):
        if not (1 <= self.ttl_seconds <= 86400 and 1 <= self.max_sessions <= 1000
                and 1 <= self.max_in_flight <= 16 and 0.05 <= self.timeout_seconds <= 180):
            raise ValueError("API limits are outside their supported ranges.")
        for origin in self.origins:
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or "*" in origin):
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths.")
            _ = parsed.port

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        origins = env.get("RAG_API_CORS_ORIGINS")
        def enabled(key):
            value = env.get(key, "0").strip().lower()
            if value not in {"0", "1", "true", "false"}:
                raise ValueError(f"{key} must be 0, 1, true, or false.")
            return value in {"1", "true"}
        return cls(
            origins=LOCAL_ORIGINS if origins is None else tuple(
                origin.strip() for origin in origins.split(",") if origin.strip()
            ),
            ttl_seconds=int(env.get("RAG_API_SESSION_TTL_SECONDS", "1800")),
            max_sessions=int(env.get("RAG_API_MAX_SESSIONS", "100")),
            max_in_flight=int(env.get("RAG_API_MAX_IN_FLIGHT", "4")),
            timeout_seconds=float(env.get("RAG_API_TIMEOUT_SECONDS", "45")),
            warmup=enabled("RAG_API_WARMUP"),
            provider_audit=enabled("RAG_API_PROVIDER_AUDIT"),
        )


class ChatBodyLimit:
    """Bound both transfer size and time before FastAPI parses a chat request."""

    def __init__(self, app, *, timeout):
        self.app = app
        self.timeout = timeout

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"].rstrip("/") != "/api/chat":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        await JSONResponse({"detail": "Chat request body is too large."}, 413)(scope, receive, send)
                        return
                    body.extend(chunk)
                    if not message.get("more_body"):
                        break
        except TimeoutError:
            await JSONResponse({"detail": "Chat request body timed out."}, 408)(scope, receive, send)
            return

        received = False

        async def replay():
            nonlocal received
            if received:
                return await receive()
            received = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


def verify_assets(bot):
    retrieval = bot.retrieval
    path, manifest = active_index(retrieval.root, index_dir=retrieval.index_dir)
    identity = catalog_identity(retrieval.root, catalog=retrieval.catalog)
    if (any(manifest.get(key) != value for key, value in identity.items())
            or not (path / "lancedb" / "chunks.lance").is_dir()):
        raise RuntimeError("The active semantic index is missing or does not match the catalog.")


def audit_provider(turn):
    """Log only fixed outcome labels. Keep session and provider payloads private."""
    diagnostics = turn.diagnostics()
    provider_names = {"gemini", "ollama", "fallback", "invalid"}
    generation_states = {"succeeded", "failed", "rejected", "not_attempted", "skipped"}
    requested = diagnostics["requested_provider"]
    actual = diagnostics["actual_provider"]
    generation = turn.generation_stage.status
    PROVIDER_AUDIT.info(
        "RAG provider outcome requested=%s actual=%s generation=%s fallback=%s",
        requested if requested in provider_names else "unknown",
        actual if actual in provider_names else "unknown",
        generation if generation in generation_states else "unknown",
        "yes" if diagnostics["fallback_triggered"] else "no",
    )


def create_app(settings=None, *, bot_factory=None):
    settings = settings if settings is not None else ApiSettings.from_env()
    bot_factory = bot_factory if bot_factory is not None else configured_bot

    @asynccontextmanager
    async def lifespan(app):
        bot = bot_factory()
        pool = ThreadPoolExecutor(max_workers=settings.max_in_flight, thread_name_prefix="rag-api")
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(pool, verify_assets, bot)
            if settings.warmup:
                # This exercises the model, LanceDB, and the broad-filter cache with local data only.
                await loop.run_in_executor(
                    pool, lambda: bot.retrieval.search(parse_query("Find kurtas under 1500"), mode="hybrid", top_k=1),
                )
            app.state.bot = bot
            app.state.pool = pool
            app.state.slots = BoundedSemaphore(settings.max_in_flight)
            app.state.sessions = SessionStore(bot.new_session, ttl=settings.ttl_seconds, capacity=settings.max_sessions)
            yield
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    api = FastAPI(
        title="IntelliMarket RAG API", version="0.6.0", lifespan=lifespan,
        description="Standalone catalog chatbot with bounded local sessions. Product prices are historical dataset records.",
    )
    api.add_middleware(ChatBodyLimit, timeout=settings.timeout_seconds)
    api.add_middleware(
        CORSMiddleware, allow_origins=list(settings.origins), allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"],
    )

    @api.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        return JSONResponse({"detail": "Invalid request. Check the session ID and message."}, 422)

    @api.middleware("http")
    async def prevent_api_caching(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @api.get("/api/health", response_model=HealthResponse, tags=["service"])
    async def health():
        return HealthResponse(status="ok", catalog_ready=True, warmup_enabled=settings.warmup,
                              dense_ready=bool(api.state.bot.retrieval.initialization_ms))

    @api.post("/api/session", response_model=SessionResponse, status_code=status.HTTP_201_CREATED,
              responses={503: {"model": ErrorResponse}}, tags=["sessions"])
    async def create_session():
        try:
            return api.state.sessions.create()
        except SessionCapacity:
            raise HTTPException(503, "Session capacity has been reached. Try again later.") from None

    @api.get("/api/session/{session_id}", response_model=SessionResponse,
             responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}, tags=["sessions"])
    async def get_session(session_id: UUID4):
        try:
            return api.state.sessions.inspect(session_id)
        except SessionMissing:
            raise HTTPException(404, NOT_FOUND) from None

    @api.delete("/api/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT,
                response_class=Response, responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
                tags=["sessions"])
    async def delete_session(session_id: UUID4):
        try:
            api.state.sessions.delete(session_id)
        except SessionMissing:
            raise HTTPException(404, NOT_FOUND) from None
        return Response(status_code=204)

    @api.post(
        "/api/chat", response_model=ChatResponse, tags=["chat"],
        responses={
            200: {"content": {"application/json": {"example": {
                "session_id": SESSION_EXAMPLE, "answer": f"Myntra recorded price: 1499. {DISCLAIMER}",
                "action": "search", "comparison": None, "historical_data_disclaimer": DISCLAIMER,
                "products": [{
                    "product_id": "17685166", "evidence_id": "myntra:17685166",
                    "name": "BUY NEW TREND Women Black Washed Lightweight Crop Denim Jacket",
                    "marketplace": "myntra", "brand": "BUY NEW TREND", "colour": "Black",
                    "categories": ["Jackets"], "prices": [
                        {"kind": "price", "amount": 1499, "amount_minor": 149900, "currency": None}
                    ],
                    "rating": None, "overall_rating": None, "rating_count": None, "product_url": None,
                    "attributes": {"fabric": ["Cotton"], "number of pockets": ["2"]},
                    "citations": [{"source_file": "myntra.csv", "record_number": 12341,
                                   "source_record_id": "17685166", "observed_at": None, "product_url": None}],
                    "conflicting_fields": [],
                }],
            }}}},
            **{code: {"model": ErrorResponse} for code in (404, 408, 409, 413, 422, 500, 503, 504)},
        },
    )
    async def chat(request: ChatRequest):
        sessions, slots = api.state.sessions, api.state.slots
        identifier = request.session_id
        try:
            entry, snapshot = sessions.borrow(identifier)
        except SessionMissing:
            raise HTTPException(404, NOT_FOUND) from None
        except SessionBusy:
            raise HTTPException(409, "A chat turn is already running for this session.") from None
        if not slots.acquire(blocking=False):
            sessions.release(identifier, entry)
            raise HTTPException(503, "The chatbot is at capacity. Try again shortly.")

        future = None
        try:
            future = asyncio.get_running_loop().run_in_executor(
                api.state.pool, api.state.bot.respond, snapshot, request.message,
            )
            turn = await asyncio.wait_for(asyncio.shield(future), settings.timeout_seconds)
            result = project_turn(identifier, turn)
            sessions.commit(identifier, entry, snapshot)
            if settings.provider_audit:
                audit_provider(turn)
            return result
        except TimeoutError:
            raise HTTPException(504, "Chat processing timed out. Try again shortly.") from None
        except SessionMissing:
            raise HTTPException(404, NOT_FOUND) from None
        except Exception:
            raise HTTPException(500, "Chat processing failed.") from None
        finally:
            def release(completed=None):
                if completed is not None and not completed.cancelled():
                    completed.exception()
                sessions.release(identifier, entry)
                slots.release()

            if future is not None and not future.done():
                future.add_done_callback(release)
            else:
                release(future)

    return api


app = create_app()
