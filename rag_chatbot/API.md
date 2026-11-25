# IntelliMarket RAG REST API

This local FastAPI service uses the same chatbot, catalog, vector index, provider configuration, and grounded response validation as the CLI.

## Run from PowerShell

From the IntelliMarket repository root:

```powershell
Set-Location rag_chatbot
New-Item -ItemType Directory -Force artifacts/tmp | Out-Null
$env:TMP = (Resolve-Path artifacts/tmp).Path
$env:TEMP = $env:TMP
.\.venv\Scripts\python.exe -B -m pip --disable-pip-version-check --no-cache-dir install 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' 'httpx>=0.27,<1'
$env:HF_HUB_OFFLINE = '1'  # The Phase 3 model is already cached
$env:RAG_API_CORS_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173'
$env:RAG_API_WARMUP = '0'
.\.venv\Scripts\python.exe -B -m uvicorn intellimarket_rag.api:app --host 127.0.0.1 --port 8001 --workers 1 --no-access-log
```

The default provider is deterministic fallback. To use Gemini, start the server from the PowerShell session where `GEMINI_API_KEY` is already set, and set `$env:RAG_PROVIDER = 'gemini'` and `$env:GEMINI_MODEL = 'gemini-3.8-flash'` before running Uvicorn. The frontend sends the session ID and message. Provider credentials, model responses, and provider diagnostics stay on the server.

Enable `$env:RAG_API_WARMUP = '1'` before startup to load the local embedding model, open LanceDB, and populate the broad-filter vector projection before the API becomes ready. This adds startup time and avoids that initialization on the first hybrid request. Warmup uses local retrieval without a Gemini call. With warmup off, SQL and FTS requests can run before the dense resources load. `GET /api/health` reports `dense_ready` after initialization.

## Frontend contract

Swagger UI is available at `http://127.0.0.1:8001/docs`. Import `http://127.0.0.1:8001/openapi.json` into an API client or use it to generate types. The schema includes request and response examples for chat.

| Method and route | Success status | Behavior |
|---|---:|---|
| `GET /api/health` | 200 | Catalog readiness, dense readiness, and warmup status. No outgoing provider request. |
| `POST /api/session` | 201 | Creates an opaque UUID and returns timestamps, busy status, and an empty message list. |
| `POST /api/chat` | 200 | Returns the answer, action, structured products, comparison, and historical-data notice for an existing session. A clarification or a search with zero products is a normal 200 response. |
| `GET /api/session/{session_id}` | 200 | Returns timestamps, busy status, and up to 12 recent message previews, each at most 350 characters. Keep full display messages in the frontend if needed. |
| `DELETE /api/session/{session_id}` | 204 | Deletes the session and returns an empty body. |

Keep the session ID for subsequent messages in the same conversation. Create a new session to start a separate conversation. Sending `/reset` clears the current conversation and keeps its session ID. Render answer text as text. Product links and citations have separate fields. Use `evidence_id` for React keys or other stable frontend identifiers, since it includes the marketplace.

Example chat body:

```json
{
  "session_id": "5151e1bc-f6b2-4d39-b781-c1d70165cabc",
  "message": "platform:myntra; id:17685166"
}
```

The example UUID illustrates the shape. Use the ID returned by `POST /api/session`. An abridged response for this real catalog item:

```json
{
  "session_id": "5151e1bc-f6b2-4d39-b781-c1d70165cabc",
  "action": "search",
  "answer": "Catalog results\n1. BUY NEW TREND Women Black Washed Lightweight Crop Denim Jacket",
  "products": [
    {
      "product_id": "17685166",
      "evidence_id": "myntra:17685166",
      "name": "BUY NEW TREND Women Black Washed Lightweight Crop Denim Jacket",
      "marketplace": "myntra",
      "colour": "Black",
      "prices": [{"kind":"price","amount":1499,"amount_minor":149900,"currency":null}],
      "rating": null,
      "attributes": {"fabric":["Cotton"],"number of pockets":["2"]},
      "product_url": null,
      "citations": [
        {"source_file":"myntra.csv","record_number":12341,"source_record_id":"17685166","observed_at":null,"product_url":null}
      ]
    }
  ],
  "comparison": null,
  "historical_data_disclaimer": "Dataset-recorded historical prices. Flipkart crawl: 2015–2016. Myntra observation date unspecified. Current prices and availability are unverified. Currency is unspecified."
}
```

- `prices[].kind` is `price` for Myntra, or `retail_price` and `discounted_price` for Flipkart. `amount_minor` is the exact dataset amount scaled by 100. The dataset does not establish currency.
- If available, `rating.raw` is the original number and `rating.display` is the two-decimal string. Missing ratings and URLs are `null`. Flipkart overall rating is supplied separately when present.
- `citations` contains accepted source row references and dates or URLs when available. `conflicting_fields` identifies recorded conflicts.
- `comparison.status` distinguishes `listed_products`, `price_by_platform`, `similar`, `ambiguous`, `no_reliable_match`, and `identical`. Only a catalog-verified identity can populate `identical_match_evidence_id`. Similar alternatives are separate products.

## Try the HTTP flow

Run this in a second PowerShell terminal while Uvicorn is running:

```powershell
$base = 'http://127.0.0.1:8001'
Invoke-RestMethod "$base/api/health"
$session = Invoke-RestMethod "$base/api/session" -Method Post
$sid = $session.session_id
$body = @{ session_id = $sid; message = "Find women's cotton kurtas under 1500" } | ConvertTo-Json -Compress
$answer = Invoke-RestMethod "$base/api/chat" -Method Post -ContentType 'application/json' -Body $body
$answer | ConvertTo-Json -Depth 12
$follow = @{ session_id = $sid; message = 'What about Myntra?' } | ConvertTo-Json -Compress
Invoke-RestMethod "$base/api/chat" -Method Post -ContentType 'application/json' -Body $follow
Invoke-RestMethod "$base/api/session/$sid"
Invoke-RestMethod "$base/api/session/$sid" -Method Delete
```

Errors use a safe JSON `detail` message. **404** means unknown, deleted, or expired session. **409** means the same session already has an active turn. **408** means the request body timed out, **413** means it exceeded 16 KiB, and **422** means invalid JSON or invalid input. **503** indicates process capacity and **504** indicates a turn exceeded its deadline. On 409 or 504, check the session's `busy` value before retrying. On 404, create a fresh session. Each message must contain 1–1,500 characters after trimming.

## Local settings and deployment limits

Process environment settings are listed in [`.env.example`](.env.example). Defaults are a 30-minute idle session TTL, 100 sessions, four simultaneous chat turns, and a 45-second chat deadline. Successful turns refresh session expiry. The request body and chat processing have separate deadlines. A worker that has already started may finish after a 504. It retains its capacity slot until completion and its late result is discarded.

**In-memory sessions and development CORS are for local integration.** Session IDs grant access to that process's session state. The service has no authentication layer, and CORS controls browser origins only. Use one Uvicorn worker. Process restarts lose sessions, and multiple workers would each have separate state. Production deployment requires authentication and authorization, TLS, rate limiting and a shared session store. Keep this development server bound to loopback. Treat session IDs as private and avoid logging them.

Run the API tests with `./.venv/Scripts/python.exe -B -X utf8 -m unittest discover -s tests -p test_api.py -v`.
