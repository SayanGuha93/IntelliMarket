"""Optional official SDK adapters. Provider errors carry fixed, safe messages."""

import json
import os
import re
from dataclasses import dataclass, field
from time import perf_counter, sleep
from urllib.parse import urlsplit


class ProviderError(RuntimeError):
    def __init__(self, message, *, reason="provider_request_failed", responded=False,
                 input_tokens=None, output_tokens=None, details=None):
        super().__init__(message)
        self.reason = reason
        self.responded = responded
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.details = details or {}


def requested_provider(provider=None, environ=None):
    env = os.environ if environ is None else environ
    name = (provider or env.get("RAG_PROVIDER") or "fallback").strip().lower()
    return name if name in {"fallback", "gemini", "ollama"} else "invalid"


@dataclass(frozen=True)
class Settings:
    provider: str = "fallback"
    model: str = ""
    key: str = field(default="", repr=False)
    host: str = "http://127.0.0.1:11434"
    timeout: float = 15
    retries: int = 1
    context_bytes: int = 14000
    output_tokens: int = 768
    thinking_level: str | None = None

    @classmethod
    def from_env(cls, provider=None, model=None, environ=None):
        env = os.environ if environ is None else environ
        name = requested_provider(provider, env)
        if name == "invalid":
            raise ProviderError("Choose fallback, gemini, or ollama.", reason="invalid_configuration")
        setting = "GEMINI_MODEL" if name == "gemini" else "OLLAMA_MODEL"
        try:
            config = cls(name, (model or env.get(setting, "")).strip(),
                         env.get("GEMINI_API_KEY", "").strip() if name == "gemini" else "",
                         env.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
                         float(env.get("RAG_TIMEOUT_SECONDS", "15")),
                         int(env.get("RAG_RETRIES", "1")),
                         int(env.get("RAG_CONTEXT_BYTES", "14000")),
                         int(env.get("RAG_OUTPUT_TOKENS", "768")),
                         (env.get("GEMINI_THINKING_LEVEL") or "").strip().lower() or None)
            host = urlsplit(config.host)
            if name == "ollama" and (host.scheme not in {"http", "https"}
                    or host.hostname not in {"127.0.0.1", "localhost", "::1"}
                    or host.username or host.password or host.query or host.fragment):
                raise ValueError()
        except ValueError:
            raise ProviderError("Invalid provider limits or Ollama loopback URL.",
                                reason="invalid_configuration") from None
        if not (1 <= config.timeout <= 60 and 0 <= config.retries <= 2
                and 4000 <= config.context_bytes <= 32000 and 128 <= config.output_tokens <= 2048):
            raise ProviderError("Provider limits are outside their allowed ranges.", reason="invalid_configuration")
        if name == "gemini" and not config.key:
            raise ProviderError("GEMINI_API_KEY is missing.", reason="missing_api_key")
        if name != "fallback" and not config.model:
            raise ProviderError(f"Select an installed or supported model using {setting}.", reason="missing_model")
        if name == "gemini" and (config.thinking_level not in {None, "low", "medium", "high", "minimal", "xhigh"}
                or (config.model.removeprefix("models/") == "gemini-3.8-flash"
                    and config.thinking_level not in {None, "low", "medium", "high"})):
            raise ProviderError("Unsupported Gemini thinking level.", reason="invalid_configuration")
        return config


@dataclass(frozen=True)
class Completion:
    data: dict
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderReply:
    text: str | None
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str | None = None
    block_reason: str | None = None
    thought_tokens: int | None = None


FINISH_REASONS = {"STOP", "MAX_TOKENS", "SAFETY", "RECITATION", "LANGUAGE", "OTHER",
                  "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "MALFORMED_FUNCTION_CALL",
                  "UNEXPECTED_TOOL_CALL", "TOO_MANY_TOOL_CALLS"}
BLOCK_REASONS = {"SAFETY", "OTHER", "BLOCKLIST", "PROHIBITED_CONTENT", "IMAGE_SAFETY", "JAILBREAK"}


def enum_name(value, allowed):
    name = getattr(value, "value", value)
    if name in {None, "", "FINISH_REASON_UNSPECIFIED", "BLOCK_REASON_UNSPECIFIED", "BLOCKED_REASON_UNSPECIFIED"}:
        return None
    return name if name in allowed else "UNKNOWN"


def gemini_reply(response):
    candidates = response.candidates or []
    candidate = candidates[0] if candidates else None
    parts = getattr(getattr(candidate, "content", None), "parts", None) or []
    text = "".join(part.text for part in parts if isinstance(part.text, str) and not part.thought)
    usage = response.usage_metadata
    return ProviderReply(
        text or None, getattr(usage, "prompt_token_count", None),
        getattr(usage, "candidates_token_count", None),
        enum_name(getattr(candidate, "finish_reason", None), FINISH_REASONS),
        enum_name(getattr(response.prompt_feedback, "block_reason", None), BLOCK_REASONS),
        getattr(usage, "thoughts_token_count", None),
    )


class DuplicateJSONKey(ValueError):
    pass


def unique_object(items):
    obj = dict(items)
    if len(obj) != len(items):
        raise DuplicateJSONKey()
    return obj


def reject_constant(_value):
    raise ValueError()


class Provider:
    """Provider-independent JSON completion contract."""

    def __init__(self, settings):
        self.settings = settings

    def complete(self, instruction, payload, schema):
        text = json.dumps(payload, ensure_ascii=False)
        if len((instruction + text + json.dumps(schema)).encode("utf-8")) > self.settings.context_bytes:
            raise ProviderError("The request exceeds the configured context budget.", reason="context_budget")
        start = perf_counter()
        for attempt in range(self.settings.retries + 1):
            try:
                reply = self.request(instruction, text, schema)
                if not isinstance(reply, ProviderReply):
                    reply = ProviderReply(*reply)
                break
            except Exception as error:
                status = getattr(error, "status_code", None) or getattr(error, "code", None)
                transient = status in (408, 429, 500, 502, 503, 504) or isinstance(error, (OSError, TimeoutError))
                transient |= any(kind.__name__ in {"TimeoutException", "NetworkError", "TransportError"}
                                 for kind in type(error).__mro__)
                if not transient or attempt == self.settings.retries:
                    reason = "rate limit" if status == 429 else "request failed"
                    codes = {401: "authentication_failed", 403: "permission_denied", 404: "model_not_found",
                             429: "rate_limited", 408: "timeout", 504: "timeout", 503: "service_unavailable"}
                    code = codes.get(status, "provider_request_failed")
                    if isinstance(error, TimeoutError) or any(
                            kind.__name__ == "TimeoutException" for kind in type(error).__mro__):
                        code = "timeout"
                    raise ProviderError(f"{self.settings.provider} {reason}.", reason=code) from None
                sleep(min(0.25 * 2**attempt, 2))
        result = reply.text
        details = {"finish_reason": reply.finish_reason, "block_reason": reply.block_reason,
                   "thought_tokens": reply.thought_tokens,
                   "response_bytes": len(result.encode("utf-8")) if isinstance(result, str) else 0}

        def rejected(category, *, reason="invalid_response", **location):
            error_details = {**details, "category": category, **location}
            raise ProviderError("Provider returned invalid structured JSON.", reason=reason,
                                responded=True, input_tokens=reply.input_tokens,
                                output_tokens=reply.output_tokens, details=error_details) from None

        if reply.block_reason or (reply.finish_reason not in {None, "STOP", "MAX_TOKENS"}):
            rejected("provider_stopped", reason="response_blocked")
        if reply.finish_reason == "MAX_TOKENS":
            rejected("output_token_limit", reason="response_truncated")
        if not isinstance(result, str) or not result.strip():
            rejected("empty_output")
        if details["response_bytes"] > self.settings.output_tokens * 16:
            rejected("response_size_limit")
        fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n\s*```", result.strip(), re.DOTALL | re.IGNORECASE)
        try:
            data = json.loads(fenced[1] if fenced else result, object_pairs_hook=unique_object,
                              parse_constant=reject_constant)
        except json.JSONDecodeError as error:
            rejected("malformed_json", line=error.lineno, column=error.colno)
        except (DuplicateJSONKey, ValueError, RecursionError) as error:
            rejected("duplicate_json_key" if isinstance(error, DuplicateJSONKey) else "invalid_json")
        if not isinstance(data, dict):
            rejected("wrong_top_level_type", path="$")
        return Completion(data, reply.input_tokens, reply.output_tokens, (perf_counter() - start) * 1000, details)


class Gemini(Provider):
    def __init__(self, settings):
        super().__init__(settings)
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(api_key=settings.key, http_options=types.HttpOptions(
            timeout=int(settings.timeout * 1000), retry_options=types.HttpRetryOptions(attempts=1),
        ))

    def request(self, instruction, payload, schema):
        level = self.settings.thinking_level
        if level is None and self.settings.model.removeprefix("models/") == "gemini-3.8-flash":
            level = "low"
        thinking = {"thinking_config": self.types.ThinkingConfig(thinking_level=level.upper())} if level else {}
        response = self.client.models.generate_content(
            model=self.settings.model, contents=payload,
            config=self.types.GenerateContentConfig(
                system_instruction=instruction, response_mime_type="application/json",
                response_json_schema=schema, max_output_tokens=self.settings.output_tokens,
                **thinking,
            ),
        )
        return gemini_reply(response)


class Ollama(Provider):
    def __init__(self, settings):
        super().__init__(settings)
        from ollama import Client

        self.client = Client(host=settings.host, timeout=settings.timeout, trust_env=False)

    def request(self, instruction, payload, schema):
        response = self.client.chat(
            model=self.settings.model, format=schema, stream=False,
            messages=[{"role": "system", "content": instruction},
                      {"role": "user", "content": payload}],
            options={"num_predict": self.settings.output_tokens,
                     "num_ctx": self.settings.context_bytes + self.settings.output_tokens + 256},
        )
        return response.message.content, response.prompt_eval_count, response.eval_count


def create_provider(settings):
    if settings.provider == "fallback":
        return None
    try:
        return {"gemini": Gemini, "ollama": Ollama}[settings.provider](settings)
    except Exception:
        raise ProviderError("Could not initialize the requested provider. Check the SDK and configuration.",
                            reason="provider_initialization_failed") from None
