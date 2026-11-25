"""HTTP adapters. Query and domain logic lives in api.services."""
import logging
import os
import re
import sqlite3
from urllib.parse import urlsplit

import requests
from django.contrib.auth import get_user_model, login, logout
from django.conf import settings
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from data_sources.google_books import GoogleBooksError, search_books
from . import services
from .serializers import GoogleCredentialSerializer, ProductSearchSerializer

logger = logging.getLogger(__name__)
HISTORICAL = "Recorded catalog observations; these are not live prices or availability."


def _error(message, status):
    return Response({"error": {"message": message}}, status=status)


def _legacy_error(message, status):
    """Keep the original flat error shape on pre-existing public API routes."""
    return Response({"error": message}, status=status)


def _legacy_result(value):
    if isinstance(value, Response) and isinstance(value.data.get("error"), dict):
        return _legacy_error(value.data["error"].get("message", "Request failed."), value.status_code)
    return value


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FileNotFoundError:
        return _error("Catalog database is unavailable.", 503)
    except sqlite3.Error as exc:
        logger.exception("Catalog query failed")
        if "no such table" in str(exc).lower():
            return _error("Catalog is not initialized with the required data tables.", 503)
        return _error("Catalog query failed.", 503)

@api_view(["GET"])
@permission_classes([AllowAny])
def get_products(request):
    search = request.query_params.get("search", "").strip()[:200]
    category = request.query_params.get("category", "").strip()[:100]
    try:
        limit = min(200, max(1, int(request.query_params.get("limit", 100))))
    except ValueError:
        return _error("limit must be an integer between 1 and 200.", 400)
    data = _run(services.product_list, search, category, limit)
    return _legacy_result(data) if isinstance(data, Response) else Response({"count": len(data), "products": data})


@api_view(["GET"])
@permission_classes([AllowAny])
def compare_prices(request):
    rows = _run(services.all_rows, """SELECT p.product_id,p.product_name,pl.source,pl.seller,pl.product_url,
            ph.price,ph.mrp,ph.discount,ph.recorded_at FROM products p JOIN product_listings pl
            ON p.product_id=pl.product_id JOIN price_history ph ON ph.id=(SELECT ph2.id FROM price_history ph2
            WHERE ph2.listing_id=pl.listing_id ORDER BY ph2.recorded_at DESC, ph2.id DESC LIMIT 1)
            ORDER BY p.product_name,ph.price""")
    if isinstance(rows, Response): return _legacy_result(rows)
    return Response({"count": len(rows), "comparisons": rows, "historical": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def get_price_history(request, listing_id):
    data = _run(services.all_rows, "SELECT listing_id,price,mrp,discount,recorded_at FROM price_history WHERE listing_id=? ORDER BY recorded_at,id", (listing_id,))
    return _legacy_result(data) if isinstance(data, Response) else Response({"listing_id": listing_id, "count": len(data), "history": data, "historical": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def get_analytics(request):
    summary = _run(services.one, "SELECT (SELECT COUNT(*) FROM products) total_products,(SELECT COUNT(*) FROM product_listings) total_listings,(SELECT COUNT(*) FROM price_history) total_observations,(SELECT COUNT(DISTINCT source) FROM product_listings) marketplace_sources")
    if isinstance(summary, Response): return _legacy_result(summary)
    prices = _run(services.all_rows, """SELECT ph.price FROM product_listings pl JOIN price_history ph ON ph.id=(
            SELECT id FROM price_history ph2 WHERE ph2.listing_id=pl.listing_id ORDER BY recorded_at DESC,id DESC LIMIT 1)""")
    if isinstance(prices, Response): return _legacy_result(prices)
    vals = [float(row["price"]) for row in prices if row["price"] is not None]
    return Response({"summary": summary, "listings_with_latest_prices": len(vals),
        "average_latest_price": round(sum(vals)/len(vals), 2) if vals else None,
        "lowest_latest_price": min(vals) if vals else None, "highest_latest_price": max(vals) if vals else None,
        "historical": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def get_category_analytics(request):
    sql = """SELECT p.category,COUNT(DISTINCT p.product_id) product_count,COUNT(DISTINCT pl.listing_id) listing_count,
        ROUND(AVG(latest.price),2) average_latest_price,MIN(latest.price) lowest_latest_price,MAX(latest.price) highest_latest_price
        FROM products p LEFT JOIN product_listings pl ON pl.product_id=p.product_id LEFT JOIN (
        SELECT ph.listing_id,ph.price FROM price_history ph JOIN (SELECT listing_id,MAX(id) latest_id FROM price_history GROUP BY listing_id) r ON r.latest_id=ph.id
        ) latest ON latest.listing_id=pl.listing_id GROUP BY p.category ORDER BY p.category"""
    data = _run(services.all_rows, sql)
    return _legacy_result(data) if isinstance(data, Response) else Response({"categories": data, "historical": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def search_google_books(request):
    result = _book_search_response(request)
    if isinstance(result, Response) and isinstance(result.data.get("error"), dict):
        return _legacy_error(result.data["error"].get("message", "Google Books search failed."), result.status_code)
    return result


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analysis_book_search(request):
    return _book_search_response(request)


def _book_search_response(request):
    query = request.query_params.get("q", "").strip()
    if not query:
        return _error("Query parameter 'q' is required.", 400)
    try:
        start = max(0, int(request.query_params.get("start_index", 0)))
        size = min(40, max(1, int(request.query_params.get("page_size", 10))))
        return Response({"provider": "Google Books", **search_books(query, start_index=start, max_results=size)})
    except ValueError:
        return _error("start_index and page_size must be valid integers.", 400)
    except GoogleBooksError:
        logger.warning("Google Books search failed; provider details are suppressed.")
        return _error("Google Books search is temporarily unavailable.", 502)


@api_view(["GET"])
@permission_classes([AllowAny])
def get_stored_google_books(request):
    query = request.query_params.get("q", "").strip()[:200]
    data = _run(services.book_list, query, 100)
    if isinstance(data, Response):
        return _legacy_result(data)
    for item in data:
        item["authors"] = services.json_value(item.get("authors"), [])
        item["categories"] = services.json_value(item.get("categories"), [])
    return Response({"provider": "Google Books", "count": len(data), "books": data})


@api_view(["GET"])
@permission_classes([AllowAny])
def get_google_books_price_history(request, volume_id):
    data = _run(services.book_history, volume_id)
    return _legacy_result(data) if isinstance(data, Response) else Response({"provider": "Google Books", "price_source": "Google Books eBookstore", "volume_id": volume_id, "count": len(data), "history": data})


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def google_login(request):
    serializer = GoogleCredentialSerializer(data=request.data)
    if not serializer.is_valid():
        return _error("A valid Google credential is required.", 400)
    credential = serializer.validated_data["credential"]
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if not client_id:
        return _error("Google sign-in is not configured.", 503)
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
        claims = id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)
        if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"} or not claims.get("sub") or claims.get("email_verified") is not True:
            return _error("Google credential is invalid or the email is not verified.", 401)
    except ImportError:
        return _error("Google token verification dependency is not installed.", 503)
    except Exception:
        return _error("Google credential could not be verified.", 401)
    User = get_user_model()
    email = (claims.get("email") or "").strip().lower()
    if not email:
        return _error("Google did not provide a verified email address.", 401)
    # Link by normalized email only when unique; the stable Google sub is persisted on user profile metadata.
    from .models import GoogleIdentity
    try:
        identity = GoogleIdentity.objects.select_related("user").filter(subject=claims["sub"]).first()
        if identity:
            user = identity.user
        else:
            matching_users = User.objects.filter(email__iexact=email)
            if matching_users.count() > 1:
                return _error("Multiple local accounts share this email; support must resolve account linking.", 409)
            user = matching_users.first()
            if user is None:
                user = User.objects.create_user(username=_unique_username(User, claims["sub"]), email=email,
                    first_name=(claims.get("given_name") or "")[:150], last_name=(claims.get("family_name") or "")[:150])
                user.set_unusable_password()
                user.save(update_fields=["password"])
            GoogleIdentity.objects.create(user=user, subject=claims["sub"], email=email)
        if identity and identity.email != email:
            identity.email = email
            identity.save(update_fields=["email"])
    except Exception:
        logger.exception("Google account provisioning failed")
        return _error("Google account could not be linked. Contact support.", 409)
    if not user.is_active:
        return _error("This account is disabled.", 403)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return Response({"authenticated": True, "user": _user_payload(user)})


def _unique_username(User, subject):
    import hashlib
    base = "google_" + hashlib.sha256(subject.encode()).hexdigest()[:24]
    username, suffix = base, 1
    while User.objects.filter(username=username).exists():
        username = f"{base}_{suffix}"; suffix += 1
    return username


def _user_payload(user):
    return {"id": user.pk, "email": user.email, "first_name": user.first_name, "last_name": user.last_name, "name": user.get_full_name()}


@api_view(["GET"])
@permission_classes([AllowAny])
def auth_me(request):
    if not request.user.is_authenticated:
        return Response({"authenticated": False, "user": None})
    return Response({"authenticated": True, "user": _user_payload(request.user)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@csrf_protect
def auth_logout(request):
    logout(request)
    return Response({"authenticated": False})


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def auth_csrf(request):
    return Response({"csrf": "cookie set"})


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    db_path = services.catalog_path()
    return Response({"status": "ok", "catalog_configured": db_path.is_file(), "catalog_path": str(db_path) if settings.DEBUG else None})


def _product_id(value):
    return bool(value and len(value) <= 200 and re.fullmatch(r"[A-Za-z0-9._:-]+", value))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analysis_index(request):
    catalog_ready = services.catalog_path().is_file()
    counts = {}
    if catalog_ready:
        queries = {"products": "SELECT COUNT(*) n FROM products", "books": "SELECT COUNT(*) n FROM google_books_catalog", "crypto": "SELECT COUNT(*) n FROM crypto_assets"}
        for key, sql in queries.items():
            result = _run(services.one, sql)
            counts[key] = None if isinstance(result, Response) else result["n"]
    else:
        counts = {"products": None, "books": None, "crypto": None}
    return Response({"categories": [
        {"key": "products", "available": counts["products"] is not None, "record_count": counts["products"], "operations": ["search", "details", "listings", "prices", "history", "insights", "prediction"], "prediction_available": False},
        {"key": "books", "available": counts["books"] is not None, "record_count": counts["books"], "operations": ["search", "details", "history", "insights"], "live_search": True},
        {"key": "crypto", "available": counts["crypto"] is not None, "record_count": counts["crypto"], "operations": ["list", "details", "history", "insights"], "prediction_available": False},
    ]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analysis_products(request):
    serializer = ProductSearchSerializer(data=request.query_params)
    if not serializer.is_valid(): return _error("Invalid product search parameters.", 400)
    params = serializer.validated_data
    data = _run(services.product_list, params.get("search", ""), params.get("category", ""), params.get("limit", 100))
    return data if isinstance(data, Response) else Response({"count": len(data), "products": data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def product_analysis(request, product_id, operation="detail"):
    if operation not in {"detail", "prices", "history", "insights", "prediction"}:
        return _error("Unknown product analysis operation.", 404)
    if not _product_id(product_id):
        return _error("Invalid product identifier.", 400)
    detail = _run(services.product_detail, product_id)
    if isinstance(detail, Response): return detail
    if detail is None: return _error("Product not found.", 404)
    if operation == "detail":
        listings = _run(services.product_listings, product_id)
        if isinstance(listings, Response): return listings
        return Response({"product": detail, "listings": listings, "historical_notice": HISTORICAL})
    if operation == "prediction":
        return Response({"product_id": product_id, "available": False, "reason": "No validated production model artifact is configured."})
    history = _run(services.product_history, product_id)
    if isinstance(history, Response): return history
    if operation == "history": return Response({"product_id": product_id, "history": history, "count": len(history), "historical_notice": HISTORICAL})
    if operation == "prices":
        prices = _run(services.product_prices, product_id)
        if isinstance(prices, Response): return prices
        return Response({"product_id": product_id, "prices": prices, "count": len(prices),
            "comparison": services.latest_price_comparison(detail, prices), "historical_notice": HISTORICAL})
    if operation == "insights": return Response({"product_id": product_id, "insights": services.price_insights(history), "historical_notice": HISTORICAL})
    return _error("Unknown product analysis operation.", 404)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analysis_books(request):
    query = request.query_params.get("q", "").strip()[:200]
    data = _run(services.book_list, query, 100)
    if isinstance(data, Response): return data
    for item in data:
        item["authors"] = services.json_value(item.get("authors"), [])
        item["categories"] = services.json_value(item.get("categories"), [])
    return Response({"count": len(data), "books": data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def book_analysis(request, volume_id, operation="detail"):
    if operation not in {"detail", "history", "insights"}:
        return _error("Unknown book analysis operation.", 404)
    if not volume_id or len(volume_id) > 200: return _error("Invalid volume identifier.", 400)
    book = _run(services.book_detail, volume_id)
    if isinstance(book, Response): return book
    if not book: return _error("Book not found in the stored catalog.", 404)
    book["authors"] = services.json_value(book.get("authors"), []); book["categories"] = services.json_value(book.get("categories"), [])
    history = _run(services.book_history, volume_id)
    if isinstance(history, Response): return history
    if operation == "history": return Response({"volume_id": volume_id, "price_source": "Google Books eBookstore", "history": history, "count": len(history)})
    if operation == "insights":
        vals = [x["google_retail_price"] for x in history if x.get("google_retail_price") is not None]
        insights = {"available": bool(vals), "observation_count": len(vals), "lowest_recorded_price": min(vals) if vals else None, "highest_recorded_price": max(vals) if vals else None, "price_source": "Google Books eBookstore"}
        return Response({"volume_id": volume_id, "insights": insights})
    return Response({"book": book, "price_source": "Google Books eBookstore; not third-party retailer pricing"})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analysis_crypto(request):
    data = _run(services.crypto_list)
    return data if isinstance(data, Response) else Response({"count": len(data), "assets": data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def crypto_analysis(request, symbol, operation="detail"):
    if operation not in {"detail", "history", "insights", "prediction"}:
        return _error("Unknown cryptocurrency analysis operation.", 404)
    if not re.fullmatch(r"[A-Za-z0-9]{2,20}", symbol or ""): return _error("Invalid cryptocurrency symbol.", 400)
    asset = _run(services.crypto_asset, symbol)
    if isinstance(asset, Response): return asset
    if not asset: return _error("Cryptocurrency asset not found.", 404)
    history = _run(services.crypto_history, symbol)
    if isinstance(history, Response): return history
    if operation == "history": return Response({"symbol": symbol.upper(), "history": history, "count": len(history), "price_unit": "provider-defined; currency is not specified by the stored schema", "is_live": False})
    if operation == "insights":
        by_exchange = {}
        for row in history:
            by_exchange.setdefault(row["source_exchange"], []).append(row)
        summaries = []
        for exchange, rows in by_exchange.items():
            vals = [float(row["last"]) for row in rows]
            change = ((vals[-1] - vals[0]) / vals[0] * 100) if len(vals) > 1 and vals[0] else None
            summaries.append({"source_exchange": exchange, "observation_count": len(vals), "first_recorded_price": vals[0], "latest_recorded_price": vals[-1], "recorded_change_percent": round(change, 4) if change is not None else None, "first_collected_at_utc": rows[0]["collected_at_utc"], "last_collected_at_utc": rows[-1]["collected_at_utc"]})
        return Response({"symbol": symbol.upper(), "available": bool(history), "observation_count": len(history), "by_exchange": summaries, "is_live": False, "price_unit": "provider-defined; currency is not specified by the stored schema"})
    if operation == "prediction": return Response({"symbol": symbol.upper(), "available": False, "reason": "No validated cryptocurrency prediction model is implemented."})
    latest = history[-1] if history else None
    return Response({"asset": asset, "latest_stored_observation": latest, "is_live": False, "price_unit": "provider-defined; currency is not specified by the stored schema"})


def _powerbi_authorized(user):
    allowed = {email.strip().lower() for email in os.getenv("POWERBI_ALLOWED_USER_EMAILS", "").split(",") if email.strip()}
    return user.is_authenticated and (not allowed or user.email.lower() in allowed or user.is_staff)


def _powerbi_token():
    tenant, client, secret = (os.getenv(key, "").strip() for key in ("PBI_TENANT_ID", "PBI_CLIENT_ID", "PBI_CLIENT_SECRET"))
    if not (tenant and client and secret):
        return None, "Power BI server credentials are not configured."
    try:
        import msal
    except ImportError:
        return None, "Power BI authentication dependency is not installed."
    try:
        app = msal.ConfidentialClientApplication(client, authority=f"https://login.microsoftonline.com/{tenant}", client_credential=secret)
        result = app.acquire_token_for_client(scopes=["https://analysis.windows.net/powerbi/api/.default"])
    except Exception:
        logger.warning("Power BI token acquisition failed; provider details are suppressed.")
        return None, "Power BI authentication failed."
    token = result.get("access_token")
    return (token, None) if token else (None, "Power BI authentication failed.")


def _powerbi_request(method, endpoint, payload=None):
    workspace = os.getenv("PBI_WORKSPACE_ID", "").strip()
    if not workspace:
        return None, _error("Power BI workspace is not configured.", 503)
    token, problem = _powerbi_token()
    if problem:
        return None, _error(problem, 503)
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace}/{endpoint.lstrip('/')}"
    try:
        response = requests.request(method, url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload, timeout=(5, 20))
    except requests.RequestException:
        logger.exception("Power BI API request failed")
        return None, _error("Power BI service is temporarily unavailable.", 502)
    if response.status_code == 404: return None, _error("Power BI report was not found in the configured workspace.", 404)
    if not response.ok:
        logger.warning("Power BI API returned status %s", response.status_code)
        return None, _error("Power BI request failed.", 502)
    try: return response.json() if response.content else {}, None
    except ValueError: return None, _error("Power BI returned an invalid response.", 502)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def powerbi_reports(request):
    if not _powerbi_authorized(request.user): return _error("You are not authorized to access Power BI reports.", 403)
    allowed = {item.strip() for item in os.getenv("PBI_REPORT_IDS", "").split(",") if item.strip()}
    if not allowed: return _error("Power BI report allowlist is not configured.", 503)
    payload, error = _powerbi_request("GET", "reports")
    if error: return error
    reports = [r for r in payload.get("value", []) if r.get("id") in allowed]
    return Response({"reports": [{k: r.get(k) for k in ("id", "name", "webUrl", "embedUrl", "datasetId")} for r in reports]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def powerbi_report(request, report_id):
    if not _powerbi_authorized(request.user): return _error("You are not authorized to access Power BI reports.", 403)
    allowed = {item.strip() for item in os.getenv("PBI_REPORT_IDS", "").split(",") if item.strip()}
    if not allowed or report_id not in allowed: return _error("Report is not in the configured allowlist.", 404)
    report, error = _powerbi_request("GET", f"reports/{report_id}")
    if error: return error
    return Response({k: report.get(k) for k in ("id", "name", "webUrl", "embedUrl", "datasetId", "reportType")})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def powerbi_embed_token(request, report_id):
    if not _powerbi_authorized(request.user): return _error("You are not authorized to access Power BI reports.", 403)
    allowed = {item.strip() for item in os.getenv("PBI_REPORT_IDS", "").split(",") if item.strip()}
    if not allowed or report_id not in allowed: return _error("Report is not in the configured allowlist.", 404)
    report, error = _powerbi_request("GET", f"reports/{report_id}")
    if error: return error
    body = {"accessLevel": "View"}
    if report.get("datasetId"): body["datasets"] = [{"id": report["datasetId"]}]
    result, error = _powerbi_request("POST", f"reports/{report_id}/GenerateToken", body)
    if error: return error
    if not result.get("token"):
        logger.error("Power BI token response omitted the embed token")
        return _error("Power BI did not return an embed token.", 502)
    return Response({"report_id": report_id, "embed_url": report.get("embedUrl"), "token": result["token"], "expiration": result.get("expiration"), "token_type": "Embed"})


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def rag_proxy(request, resource="", session_id=None):
    return _rag_request(request, request.method, resource, session_id)


def _rag_request(request, method, resource, session_id=None):
    from uuid import UUID
    from .models import RAGSessionOwner
    base = os.getenv("RAG_API_URL", "http://127.0.0.1:8001").rstrip("/")
    parsed_base = urlsplit(base)
    loopback_hosts = {"localhost", "127.0.0.1", "::1"}
    trusted_http_hosts = loopback_hosts | {host.strip().lower() for host in os.getenv("RAG_API_ALLOWED_HOSTS", "").split(",") if host.strip()}
    if (parsed_base.scheme not in {"http", "https"} or not parsed_base.hostname
            or parsed_base.username or parsed_base.password
            or (parsed_base.scheme == "http" and parsed_base.hostname.lower() not in trusted_http_hosts)):
        return _error("RAG service URL must use HTTPS or loopback HTTP.", 503)
    path = "/api/" + resource.strip("/")
    if session_id is not None:
        path += "/" + session_id
    target_session = session_id
    if resource == "chat" and method == "POST":
        target_session = request.data.get("session_id")
    if target_session:
        try:
            target_session = UUID(str(target_session))
        except (TypeError, ValueError):
            return _error("Invalid chat session identifier.", 400)
        owner = RAGSessionOwner.objects.filter(session_id=target_session).first()
        if owner is None or owner.user_id != request.user.pk:
            return _error("Chat session not found.", 404)
    try:
        response = requests.request(method, base + path, json=request.data if method == "POST" else None, params=request.query_params, timeout=(3, 50), allow_redirects=False)
    except requests.RequestException:
        logger.exception("RAG service unavailable")
        return _error("Chat service is temporarily unavailable.", 503)
    if response.status_code == 204:
        if resource == "session" and method == "DELETE":
            RAGSessionOwner.objects.filter(session_id=target_session, user=request.user).delete()
        return Response(status=204)
    try: payload = response.json()
    except ValueError: return _error("Chat service returned an invalid response.", 502)
    if resource == "session" and method == "POST" and response.status_code == 201:
        try:
            session_uuid = UUID(str(payload["session_id"]))
            RAGSessionOwner.objects.create(session_id=session_uuid, user=request.user)
        except Exception:
            logger.exception("Could not record RAG session ownership")
            try: requests.delete(f"{base}/api/session/{payload['session_id']}", timeout=(3, 10))
            except (requests.RequestException, KeyError): pass
            return _error("Chat session could not be initialized.", 503)
    return Response(payload, status=response.status_code)
