# IntelliMarket chatbot frontend handover

FastAPI exposes the standalone chatbot. SQLite applies verified structured filters and FTS5 keyword search. LanceDB supplies semantic candidates when the adaptive router needs them. The chatbot preserves context within each session and validates evidence before rendering. Gemini runs server-side on eligible turns. Exact lookups and other deterministic routes may complete locally.

## Install and start

From the IntelliMarket repository root, use the existing Phase 6 virtual environment, catalog, index and model cache.

~~~powershell
Set-Location rag_chatbot
.\.venv\Scripts\python.exe -B -m pip --disable-pip-version-check --no-cache-dir install 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' 'httpx>=0.27,<1'
$env:RAG_PROVIDER = 'fallback'
$env:RAG_API_CORS_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173'
$env:RAG_API_WARMUP = '1'
$env:HF_HUB_OFFLINE = '1'
.\.venv\Scripts\python.exe -B -m uvicorn intellimarket_rag.api:app --host 127.0.0.1 --port 8001 --workers 1 --no-access-log --log-level info
~~~

Set offline mode only when the embedding model is already cached. Gemini requires google-genai>=1,<3 in the same environment. Settings come from the server process environment. The example env file documents them.

| Variables | Purpose |
|---|---|
| RAG_PROVIDER | fallback (default), gemini or ollama |
| GEMINI_API_KEY, GEMINI_MODEL, GEMINI_THINKING_LEVEL | Private server credential, model and optional thinking setting |
| OLLAMA_HOST, OLLAMA_MODEL | Optional local provider configuration |
| RAG_TIMEOUT_SECONDS, RAG_RETRIES | Provider timeout and retry count, 15 seconds and 1 by default |
| RAG_CONTEXT_BYTES, RAG_OUTPUT_TOKENS | Provider context and output limits, 14,000 bytes and 768 tokens by default |
| RAG_API_CORS_ORIGINS | Comma-separated origin allowlist. Defaults include localhost and 127.0.0.1 on ports 3000 and 5173. |
| RAG_API_SESSION_TTL_SECONDS, RAG_API_MAX_SESSIONS | Idle session lifetime and capacity, 1,800 seconds and 100 sessions by default |
| RAG_API_MAX_IN_FLIGHT, RAG_API_TIMEOUT_SECONDS | Chat concurrency and deadline, 4 turns and 45 seconds by default |
| RAG_API_WARMUP | Set to 1 to initialise dense retrieval before serving. Defaults to 0. |
| RAG_API_PROVIDER_AUDIT | Set to 1 for coarse provider outcomes in server logs. Defaults to 0. |
| HF_HUB_OFFLINE | Set to 1 when using an existing model cache. |

[Swagger UI](http://127.0.0.1:8001/docs) · [OpenAPI JSON](http://127.0.0.1:8001/openapi.json)

## Endpoint examples

The example UUID and timestamps illustrate one session. Use the UUID returned by the server.

### GET /api/health

Empty request. Example HTTP 200 after warmup. Dense readiness can be false until the first dense turn when warmup is disabled. Health does not contact Gemini.

~~~json
{"status":"ok","catalog_ready":true,"dense_ready":true,"warmup_enabled":true}
~~~

### POST /api/session

Empty request. Example HTTP 201.

~~~json
{"session_id":"5151e1bc-f6b2-4d39-b781-c1d70165cabc","created_at":"2026-11-25T10:00:00Z","expires_at":"2026-11-25T10:30:00Z","busy":false,"recent_messages":[]}
~~~

### POST /api/chat

Send application/json. Example request.

~~~json
{"session_id":"5151e1bc-f6b2-4d39-b781-c1d70165cabc","message":"platform:myntra; id:17685166"}
~~~

Example HTTP 200 using a real catalog product.

~~~json
{
  "session_id": "5151e1bc-f6b2-4d39-b781-c1d70165cabc",
  "answer": "Catalog results\n1. BUY NEW TREND Women Black Washed Lightweight Crop Denim Jacket (myntra, 17685166)\n   Myntra recorded price: 1499\n   Brand: BUY NEW TREND\n   Colour: Black\n   Closure: Snap Button\n   Fabric: Cotton\n   Recorded rating unavailable.\n   [myntra:17685166 · myntra.csv · row 12341]\nDataset-recorded historical prices. Flipkart crawl: 2015–2016. Myntra observation date unspecified. Current prices and availability are unverified. Currency is unspecified.",
  "action": "search",
  "products": [{
    "product_id": "17685166",
    "evidence_id": "myntra:17685166",
    "name": "BUY NEW TREND Women Black Washed Lightweight Crop Denim Jacket",
    "marketplace": "myntra",
    "brand": "BUY NEW TREND",
    "colour": "Black",
    "categories": ["Jackets"],
    "prices": [{"kind":"price","amount":1499.0,"amount_minor":149900,"currency":null}],
    "rating": null,
    "overall_rating": null,
    "rating_count": null,
    "attributes": {
      "body shape id":["333,424"],"closure":["Snap Button"],"collar":["Spread Collar"],
      "fabric":["Cotton"],"features":["Lightweight"],"hemline":["Curved"],"length":["Crop"],
      "lining fabric":["Cotton"],"number of pockets":["2"],"occasion":["Casual"],
      "pattern":["Solid"],"print or pattern type":["Washed"],"sleeve length":["Three-Quarter Sleeves"],
      "surface styling":["Faux Fur Trim"],"sustainable":["Regular"],"technology present":["No"],
      "type":["Denim Jacket"],"wash care":["Machine Wash"],"weave type":["Woven"]
    },
    "product_url": null,
    "citations": [{"source_file":"myntra.csv","record_number":12341,"source_record_id":"17685166","observed_at":null,"product_url":null}],
    "conflicting_fields": []
  }],
  "comparison": null,
  "historical_data_disclaimer": "Dataset-recorded historical prices. Flipkart crawl: 2015–2016. Myntra observation date unspecified. Current prices and availability are unverified. Currency is unspecified."
}
~~~

A non-null comparison contains status, product_evidence_ids, anchor_evidence_id and identical_match_evidence_id. Join those IDs to products by evidence_id. Status can be listed_products, price_by_platform, similar, ambiguous, no_reliable_match or identical. Display similar products as alternatives. Use the verified identity field for identical matches.

### GET /api/session/{session_id}

Empty request with the session UUID in the URL. Example HTTP 200 after a reset turn.

~~~json
{"session_id":"5151e1bc-f6b2-4d39-b781-c1d70165cabc","created_at":"2026-11-25T10:00:00Z","expires_at":"2026-11-25T10:30:04Z","busy":false,"recent_messages":[]}
~~~

Ordinary chat history has objects with role (user or assistant) and content (text preview). The server returns up to 12 previews of at most 350 characters. Keep full responses in frontend state when needed.

### DELETE /api/session/{session_id}

Empty request with the session UUID in the URL. HTTP 204 contains zero response-body bytes. Any subsequent lookup or chat for that UUID returns HTTP 404.

## Sessions, loading and errors

- Reuse one ID for follow-ups such as “What about Myntra?” and “Only black.” Start a fresh session for a new conversation. Send /reset to clear context on the current ID.
- Successful turns extend the idle expiry. Reading the session leaves its expiry unchanged.
- Show a startup state until health is reachable. Show loading and disable a second send while a chat is pending. A 200 with zero products or action "clarify" is a normal result.
- Errors use a JSON detail string. For 404 (unknown, expired or deleted), create a new session and let the user decide whether to resend. For 409 (busy) or 504 (turn timeout), check busy before retrying. Handle 408 for request-body timeout, 413 for bodies larger than 16 KiB, 422 for invalid input, 503 for capacity and 500 for processing failure. Messages must contain 1–1,500 characters after trimming.

### JavaScript fetch

~~~javascript
const base = "http://127.0.0.1:8001";

async function request(path, method = "GET", body) {
  const options = { method };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(base + path, options);
  if (response.status === 204) return;
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw Object.assign(new Error(payload?.detail ?? "Request failed"), {
      status: response.status,
    });
  }
  return payload;
}

const health = () => request("/api/health");
const createSession = () => request("/api/session", "POST");
const sendMessage = (session_id, message) =>
  request("/api/chat", "POST", { session_id, message });
const getSession = (id) => request("/api/session/" + encodeURIComponent(id));
const deleteSession = (id) => request("/api/session/" + encodeURIComponent(id), "DELETE");

const session = await createSession();
const result = await sendMessage(session.session_id, "Find women's cotton kurtas under 1500");
const followUp = await sendMessage(session.session_id, "What about Myntra?");
~~~

## Product cards

| UI element | Fields |
|---|---|
| Card key, title, marketplace, source ID | evidence_id, name, marketplace, product_id |
| Brand, colour and category | brand, colour, categories |
| Recorded price | prices[].amount and prices[].kind. Kind distinguishes Myntra price, Flipkart retail price and Flipkart discounted price. amount_minor is the source amount scaled by 100. |
| Rating | rating.display and overall_rating.display are two-decimal strings. Use raw for numerical operations and rating_count for the count. |
| Specifications | attributes maps names to arrays of values. conflicting_fields flags disagreements. |
| Sources and links | citations lists source file, record number, source ID, observation timestamp and URL where available. Offer product_url only if present and HTTP(S). |

Render content as text and hide unavailable optional fields. Display historical_data_disclaimer beside products and comparisons. Flipkart prices were crawled in 2015–2016. The Myntra snapshot has no established observation date. Current prices, availability and currency are unverified.

## PowerShell UTF-8 and private Gemini verification

The API sends application/json with UTF-8 bytes. The citation dot is C2 B7 and the date-range dash is E2 80 93. Interpreting them as Windows-1252 reproduces the garbled output. Browser response.json() decodes correctly. For Windows PowerShell, decode the HTTP bytes before parsing JSON.

For live verification, set these values in the server terminal where the credential is already configured, and restart Uvicorn using the startup command above.

~~~powershell
$env:RAG_PROVIDER = 'gemini'
$env:GEMINI_MODEL = 'gemini-3.8-flash'
$env:RAG_API_PROVIDER_AUDIT = '1'
.\.venv\Scripts\python.exe -B -m uvicorn intellimarket_rag.api:app --host 127.0.0.1 --port 8001 --workers 1 --no-access-log --log-level info
~~~

In a second terminal, run the following. It also works against a fallback server for checking Unicode.

~~~powershell
$base = 'http://127.0.0.1:8001'
$session = Invoke-RestMethod "$base/api/session" -Method Post
$body = @{session_id = $session.session_id; message = "Find women's cotton kurtas under 1500"} | ConvertTo-Json -Compress
Add-Type -AssemblyName System.Net.Http
$http = [System.Net.Http.HttpClient]::new()
try {
    $content = [System.Net.Http.StringContent]::new($body, [Text.Encoding]::UTF8, 'application/json')
    $response = $http.PostAsync("$base/api/chat", $content).GetAwaiter().GetResult()
    $response.EnsureSuccessStatusCode() | Out-Null
    $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    $utf8 = [Text.UTF8Encoding]::new($false, $true)
    $decoded = $utf8.GetString($bytes) | ConvertFrom-Json
    $decoded.answer
    $decoded.historical_data_disclaimer
} finally {
    $http.Dispose()
}
Invoke-RestMethod "$base/api/session/$($session.session_id)" -Method Delete
~~~

For a successful Gemini answer, the server logs **requested=gemini actual=gemini generation=succeeded fallback=no**. A deterministic route can log **actual=fallback generation=not_attempted fallback=no**. The audit emits fixed labels only, and the frontend receives the regular chat response.

## Deployment boundary

Use a single loopback worker for development. Session IDs act as access handles and should stay private. Restarts clear in-memory sessions and each worker holds separate state. CORS is a development browser allowlist. Production requires authenticated session ownership, TLS, rate limits and shared session storage. A timed-out worker can retain its capacity slot until it finishes, and its late result is discarded.
