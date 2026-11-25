from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    # Existing public compatibility endpoints.
    path("products/", views.get_products, name="get_products"),
    path("compare/", views.compare_prices, name="compare_prices"),
    path("price-history/<int:listing_id>/", views.get_price_history, name="get_price_history"),
    path("analytics/", views.get_analytics, name="get_analytics"),
    path("analytics/categories/", views.get_category_analytics, name="get_category_analytics"),
    path("books/search/", views.search_google_books, name="search_google_books"),
    path("books/", views.get_stored_google_books, name="get_stored_google_books"),
    path("books/<str:volume_id>/price-history/", views.get_google_books_price_history, name="get_google_books_price_history"),
    # Session-based Google sign-in.
    path("auth/google/", views.google_login, name="google_login"),
    path("auth/csrf/", views.auth_csrf, name="auth_csrf"),
    path("auth/me/", views.auth_me, name="auth_me"),
    path("auth/logout/", views.auth_logout, name="auth_logout"),
    # Authenticated analysis APIs.
    path("analysis/", views.analysis_index, name="analysis_index"),
    path("analysis/products/", views.analysis_products, name="analysis_products"),
    path("analysis/products/<str:product_id>/", views.product_analysis, name="product_analysis"),
    path("analysis/products/<str:product_id>/<str:operation>/", views.product_analysis, name="product_analysis_operation"),
    path("analysis/books/", views.analysis_books, name="analysis_books"),
    path("analysis/books/search/", views.analysis_book_search, name="analysis_book_search"),
    path("analysis/books/<str:volume_id>/", views.book_analysis, name="book_analysis"),
    path("analysis/books/<str:volume_id>/<str:operation>/", views.book_analysis, name="book_analysis_operation"),
    path("analysis/crypto/", views.analysis_crypto, name="analysis_crypto"),
    path("analysis/crypto/<str:symbol>/", views.crypto_analysis, name="crypto_analysis"),
    path("analysis/crypto/<str:symbol>/<str:operation>/", views.crypto_analysis, name="crypto_analysis_operation"),
    # Authenticated gateway to the independently hosted RAG process.
    path("chat/health/", views.rag_proxy, {"resource": "health"}, name="chat_health"),
    path("chat/session/", views.rag_proxy, {"resource": "session"}, name="chat_create_session"),
    path("chat/session/<str:session_id>/", views.rag_proxy, {"resource": "session"}, name="chat_get_or_delete_session"),
    path("chat/chat/", views.rag_proxy, {"resource": "chat"}, name="chat_send"),
    path("powerbi/reports/", views.powerbi_reports, name="powerbi_reports"),
    path("powerbi/reports/<str:report_id>/", views.powerbi_report, name="powerbi_report"),
    path("powerbi/reports/<str:report_id>/embed-token/", views.powerbi_embed_token, name="powerbi_embed_token"),
]
