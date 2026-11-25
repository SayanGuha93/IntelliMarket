"""Interactive terminal client for the shared chatbot service."""

import json
import sys

from .chat import Chatbot, Router, safe_reason
from .providers import ProviderError, Settings, create_provider, requested_provider


def configured_bot(root=None, *, provider=None, model=None, mode="adaptive", rerank=False,
                   keyword_limit=4, device="cpu", threads=6, top_k=5, catalog=None, index_dir=None,
                   llm_intent=False):
    requested = requested_provider(provider)
    failure = None
    try:
        adapter = create_provider(Settings.from_env(requested, model))
    except ProviderError as error:
        failure = safe_reason(error.reason)
        print(f"Provider unavailable. Using deterministic fallback ({failure}).", file=sys.stderr)
        adapter = None
    return Chatbot(root, provider=adapter, router=Router(mode, rerank, keyword_limit),
                   device=device, threads=threads, top_k=top_k, catalog=catalog, index_dir=index_dir,
                   requested_provider=requested, initialization_failure=failure, intent_assistance=llm_intent)


def interactive(root, *, debug=False, **options):
    bot = configured_bot(root, **options)
    session = bot.new_session()
    print(f"IntelliMarket catalog chat ({bot.configured_provider}). Use /reset or /exit.")
    if debug:
        print(json.dumps({"requested_provider": bot.requested_provider,
                          "configured_provider": bot.configured_provider,
                          "startup_fallback_reason": bot.initialization_failure}))
    while True:
        try:
            text = input("You> ")
            if text.strip().lower() in {"/exit", "/quit", "exit", "quit"}:
                break
            turn = bot.respond(session, text)
            print(turn.answer)
            if debug:
                print(json.dumps(turn.diagnostics(), ensure_ascii=True))
        except (EOFError, KeyboardInterrupt):
            print()
            break
    print("Goodbye.")
