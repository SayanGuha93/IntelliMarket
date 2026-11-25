# IntelliMarket backend

This backend keeps Django as the application API and reuses the existing `prices.db` catalog. Django reads that database through parameterized, read-only SQLite connections. It does not map or migrate the product, Google Books, or crypto tables. Django's own database remains separate and stores auth/session tables, Google identity links, and RAG session ownership records.

## Architecture

- `config/`: settings and top-level routes.
- `api/views.py`: HTTP, authentication, authorization, and upstream adapter layer.
- `api/services.py`: read-only SQL and analysis calculations over the existing catalog.
- `api/serializers.py`: validation for externally supplied auth data.
- `api/models.py`: Google subject identity links and Django-side RAG session ownership.
- `database/schema.sql`: existing catalog schema; no schema changes were made for analysis APIs.
- `data_sources/`: existing Google Books and crypto data ingestion clients.
- `rag_chatbot/`: separate FastAPI retrieval service.
- `powerbi/`: local Power BI project and frontend reference; Power BI Service publishing is external.

## Local setup

Use Python 3.11 or newer. From the repository root, create a virtual environment and install `requirements.txt`; use `.env.example` as a variable checklist and export its values into the process (Django does not load `.env` files itself). Set `DJANGO_SECRET_KEY` to a private random value even for local work. `DJANGO_DEBUG` defaults to false and startup fails if the secret is missing; set `DJANGO_DEBUG=true` explicitly for local HTTP development.

Run Django commands from `backend/`:

```powershell
python manage.py check
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

`migrate` only creates Django's normal auth/session tables and the app's Google identity and RAG ownership tables. It does not modify `prices.db`. Point `INTELLIMARKET_DB_PATH` at the existing catalog file; a relative value is resolved from the repository root. The web API opens the catalog with SQLite `mode=ro` and will not create an empty replacement database.

The RAG service remains a separate process. Follow `rag_chatbot/API.md` for its catalog/index and provider setup. Set `RAG_API_URL` for Django. Bind the FastAPI service to loopback or a private service network and do not expose port 8001 publicly: direct FastAPI routes have no Django authentication. For a private HTTP service hostname, set its exact hostname (without port) in `RAG_API_ALLOWED_HOSTS`; HTTPS URLs are accepted directly. Use one worker because its actual chat/session state is in memory. Django's ownership index prevents a logged-in user from using another user's session through the gateway, but it cannot make the FastAPI process state durable. Restarting RAG invalidates its sessions; multiple workers have separate session stores.

## Authentication

The API uses Django session cookies, suitable for a same-site frontend. The frontend first requests `GET /api/auth/csrf/` with credentials enabled, then sends the returned `csrftoken` cookie in `X-CSRFToken` when calling `POST /api/auth/google/` or `POST /api/auth/logout/`. Google Identity Services sends an ID token in the `credential` field. Django verifies the JWT signature, issuer, expiry, and audience using Google's verification library and `GOOGLE_CLIENT_ID`; no client secret is needed for this ID-token flow.

On first sign-in, the backend creates a Django user with an unusable password and records the stable Google `sub` in `GoogleIdentity`. Later sign-ins resolve by that subject. A previously existing account with the same verified email is linked to the Google subject. Disabled accounts are rejected. The `/api/auth/me/` response reports the active session. Logout flushes the Django session. Analysis, chat, and Power BI routes require authentication; legacy product and book routes remain public for compatibility.

Example:

```http
POST /api/auth/google/
Content-Type: application/json
X-CSRFToken: <csrf-cookie-value>
Cookie: csrftoken=<csrf-cookie-value>
```

```json
{"credential":"<Google ID token>"}
```

Success returns `{"authenticated":true,"user":{"id":1,"email":"...","first_name":"...","last_name":"...","name":"..."}}`. A missing client ID returns 503. Invalid or expired credentials return 401. CORS and CSRF origins must be explicit. For a cross-site frontend, configure HTTPS, `SESSION_COOKIE_SAMESITE=None`, and secure cookies; prefer deploying frontend and API under the same site where possible.

## API routes

All routes are relative to `/api/`. Analysis, chat, and Power BI require a logged-in Django session. `GET /auth/csrf/` sets the CSRF cookie; `GET /auth/me/` is public and returns an unauthenticated status when no session exists.

| Method | Route | Access | Purpose |
|---|---|---|---|
| GET | `/health/` | Public | Django liveness and whether the catalog file exists |
| POST | `/auth/google/` | Public + CSRF | Verify Google ID token, create/retrieve user, start session |
| GET | `/auth/me/` | Public | Current authentication status and profile |
| POST | `/auth/logout/` | Authenticated + CSRF | Flush current session |
| GET | `/products/` | Public | Existing product search; optional `search`, `category`, `limit` |
| GET | `/compare/` | Public | Latest recorded price per listing |
| GET | `/price-history/{listing_id}/` | Public | Listing observations |
| GET | `/analytics/` | Public | Existing catalog summary |
| GET | `/analytics/categories/` | Public | Category summary |
| GET | `/books/` | Public | Stored Google Books catalog search (`q`) |
| GET | `/books/search/` | Public | Live Google Books search (`q`, `start_index`, `page_size`) |
| GET | `/books/{volume_id}/price-history/` | Public | Stored Google Books eBookstore observations |
| GET | `/analysis/` | Authenticated | Supported domains and operations |
| GET | `/analysis/products/` | Authenticated | Product search |
| GET | `/analysis/products/{product_id}/` | Authenticated | Product details and listings |
| GET | `/analysis/products/{product_id}/prices/` | Authenticated | Latest recorded prices by listing/source |
| GET | `/analysis/products/{product_id}/history/` | Authenticated | All recorded product history |
| GET | `/analysis/products/{product_id}/insights/` | Authenticated | Min/max/average and first-to-latest recorded change |
| GET | `/analysis/products/{product_id}/prediction/` | Authenticated | Explicit unavailable status; no deployed validated artifact found |
| GET | `/analysis/books/` | Authenticated | Stored book search (`q`) |
| GET | `/analysis/books/search/` | Authenticated | Live Google Books search |
| GET | `/analysis/books/{volume_id}/` | Authenticated | Stored book details |
| GET | `/analysis/books/{volume_id}/history/` | Authenticated | Google Books eBookstore price history |
| GET | `/analysis/books/{volume_id}/insights/` | Authenticated | Min/max of stored retail prices when available |
| GET | `/analysis/crypto/` | Authenticated | Stored crypto assets and observation counts |
| GET | `/analysis/crypto/{symbol}/` | Authenticated | Asset and latest stored observation |
| GET | `/analysis/crypto/{symbol}/history/` | Authenticated | Stored history, exchange and timestamps |
| GET | `/analysis/crypto/{symbol}/insights/` | Authenticated | First/latest stored price and derived change |
| GET | `/analysis/crypto/{symbol}/prediction/` | Authenticated | Explicit unavailable status; no crypto model exists |
| GET | `/chat/health/` | Authenticated | Proxy to private RAG health endpoint |
| POST | `/chat/session/` | Authenticated + CSRF | Create RAG session and persist its Django owner |
| GET/DELETE | `/chat/session/{session_id}/` | Authenticated | Read/delete only the caller's session |
| POST | `/chat/chat/` | Authenticated + CSRF | Send chat message for a caller-owned session |
| GET | `/powerbi/reports/` | Authenticated + allowlist | List reports in configured workspace |
| GET | `/powerbi/reports/{report_id}/` | Authenticated + allowlist | Retrieve report metadata |
| POST | `/powerbi/reports/{report_id}/embed-token/` | Authenticated + allowlist + CSRF | Create short-lived Power BI embed token |

Analysis responses use JSON objects and `{error:{message}}` for API-level failures. Missing records return 404; missing catalog configuration or tables return 503; external provider failures return 502. Database errors are logged server-side without returning SQL or local paths.

Product insight response shape (field values come from the requested catalog records):

```json
{
  "product_id": "<database product_id>",
  "insights": {
    "available": true,
    "observations": "<count from database>",
    "lowest_price": "<calculated from stored prices>",
    "highest_price": "<calculated from stored prices>",
    "average_price": "<calculated from stored prices>",
    "first_price": "<earliest stored price>",
    "latest_price": "<latest stored price>",
    "price_change": "<latest minus earliest stored price>",
    "is_live": false
  },
  "historical_notice": "Recorded catalog observations; these are not live prices or availability."
}
```

Crypto insight field shape (each exchange is summarized independently because the stored price unit/currency is provider-defined; angle-bracket values are placeholders):

```json
{
  "symbol": "BTC",
  "available": true,
  "observation_count": 2,
  "by_exchange": [
    {
      "source_exchange": "<stored exchange>",
      "observation_count": "<count from database>",
      "first_recorded_price": "<earliest stored value>",
      "latest_recorded_price": "<latest stored value>",
      "recorded_change_percent": "<calculated from stored values>",
      "first_collected_at_utc": "<stored collection timestamp>",
      "last_collected_at_utc": "<stored collection timestamp>"
    }
  ],
  "is_live": false,
  "price_unit": "provider-defined; currency is not specified by the stored schema"
}
```

Example Power BI embed response after external setup:

```json
{
  "report_id": "<configured-report-id>",
  "embed_url": "https://app.powerbi.com/reportEmbed?...",
  "token": "<short-lived-embed-token>",
  "expiration": "<Microsoft-issued-expiration>",
  "token_type": "Embed"
}
```

## Data and interpretation

Products and listings come from `products`, `product_listings`, and `price_history`. Book data comes from `google_books_catalog` and `google_books_price_history`. Crypto data comes from `crypto_assets` and `crypto_market_history`. No schema migration is needed for the read APIs. `INTELLIMARKET_DB_PATH` is shared with `database.connection` so existing ingestion can target the same file.

Product values are recorded observations, not live quotes. Google Books eBookstore data is labeled as such and is separate from third-party retailer pricing. Crypto stores provider-defined `last` and `last_btc` values; the existing schema does not identify a quote currency, so the API explicitly does not claim one. Provider time and collection time are returned separately. No prediction endpoint fabricates a result.

## Google Cloud setup

Create an OAuth client for Google Identity Services and set `GOOGLE_CLIENT_ID`. Add the actual frontend origins to the OAuth client. Set `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` to those exact origins. No Google client secret belongs in this ID-token verification flow. Configure API quotas and authorized domains in the Google project as required by deployment.

## Power BI setup and limits

The code uses app-owns-data REST API embedding. Publish the existing PBIP report manually to a restricted Power BI workspace first. Configure a Microsoft Entra application/service principal, enable service-principal API access in the tenant, grant the principal workspace access, and provide `PBI_TENANT_ID`, `PBI_CLIENT_ID`, `PBI_CLIENT_SECRET`, `PBI_WORKSPACE_ID`, and an explicit comma-separated `PBI_REPORT_IDS`. Optionally set `POWERBI_ALLOWED_USER_EMAILS`; when unset, any authenticated Django user may access the configured report allowlist. Staff users can pass the email allowlist. Deploy over HTTPS.

Embedding requires the correct Power BI tenant settings and supported capacity/licensing for app-owns-data; website viewers do not each need a Power BI Pro license in this mode, but the embedding capacity is a paid deployment requirement. Confirm exact capacity, tenant, and workspace eligibility with the tenant administrator. The local PBIP is not a published report, so endpoints return configuration errors until the cloud resources exist. Embed tokens are returned to authorized clients and must be treated as short-lived bearer credentials. Microsoft app credentials and Microsoft access tokens never leave Django.

## Deployment

Set `DJANGO_DEBUG=false`, a strong `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, explicit production CORS/CSRF origins, and secure session settings. Django redirects to HTTPS and marks session/CSRF cookies secure when debug is disabled. Do not deploy the `.env.example` values. An example Render web command for the Django API is `cd backend && gunicorn config.wsgi:application`; add `gunicorn` to deployment dependencies if using that server. Run migrations as a release step (`python manage.py migrate`). Do not run ingestion from web workers.

SQLite works only when the database file is present and the host provides persistent storage. Ephemeral container filesystems can lose `prices.db` and Django auth state on restart/redeploy. Mount persistent storage for both files or move to managed PostgreSQL and explicitly adapt the existing catalog access layer. This repository does not verify a Render deployment or persistent disk configuration. Run the RAG service as a private service with one worker; do not route external traffic directly to it.

## Tests

From `backend/`, run `python manage.py check` and `python manage.py test api`. Power BI and Google network calls should be tested with mocks; these do not prove tenant credentials, quotas, OAuth origins, or embedding capacity work. RAG service tests remain in `rag_chatbot/tests`; run those using the environment described in `rag_chatbot/API.md`.

## Known limitations

- Google sign-in requires an OAuth client ID and the `google-auth` dependency.
- Session auth requires CSRF and same-site cookie configuration from the frontend.
- Existing public product/book routes remain public for compatibility; use `/analysis/` routes for authenticated access.
- RAG chat contents and sessions remain process-memory data and are lost on service restart. The ownership index is durable in Django but does not persist chat history.
- Crypto and product prediction APIs explicitly report unavailable; no validated crypto model or deployed product artifact exists.
- Power BI requires a published report and externally provisioned Entra, workspace, tenant, and capacity settings.
