from django.urls import path
from .views import get_products, compare_prices,get_price_history,get_analytics, get_category_analytics

urlpatterns = [
    path("products/", get_products, name="get_products"),
    path("compare/", compare_prices, name="compare_prices"),
    path("price-history/<int:listing_id>/", get_price_history, name="get_price_history"),
    path("analytics/", get_analytics, name="get_analytics"),
    path("analytics/categories/", get_category_analytics, name="get_category_analytics"),
]