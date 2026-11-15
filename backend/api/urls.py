from django.urls import path
from .views import (get_products, compare_prices, get_price_history,
                    get_analytics, get_category_analytics,
                    search_google_books, get_stored_google_books,
                    get_google_books_price_history)

urlpatterns = [
    path("products/", get_products, name="get_products"),
    path("compare/", compare_prices, name="compare_prices"),
    path("price-history/<int:listing_id>/", get_price_history, name="get_price_history"),
    path("analytics/", get_analytics, name="get_analytics"),
    path("analytics/categories/", get_category_analytics, name="get_category_analytics"),
    path("books/search/", search_google_books, name="search_google_books"),
    path("books/", get_stored_google_books, name="get_stored_google_books"),
    path("books/<str:volume_id>/price-history/", get_google_books_price_history, name="get_google_books_price_history"),
]
