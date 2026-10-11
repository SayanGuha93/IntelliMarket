
import requests
import streamlit as st
import pandas as pd

API_BASE = "http://127.0.0.1:8000/api"

st.set_page_config(
    page_title="IntelliMarket",
    page_icon="🛒",
    layout="wide"
)

st.title("IntelliMarket")
st.caption("Intelligent Product Price Comparison and Analytics")

try:
    response = requests.get(f"{API_BASE}/analytics/", timeout=10)
    response.raise_for_status()
    analytics = response.json()

    summary = analytics["summary"]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Products", summary["total_products"])
    col2.metric("Marketplace Listings", summary["total_listings"])
    col3.metric("Price Observations", summary["total_observations"])
    col4.metric("Marketplace Sources", summary["marketplace_sources"])

    col5, col6, col7 = st.columns(3)

    col5.metric("Average Latest Price", analytics["average_latest_price"])
    col6.metric("Lowest Latest Price", analytics["lowest_latest_price"])
    col7.metric("Highest Latest Price", analytics["highest_latest_price"])

except requests.RequestException as error:
    st.error("Unable to connect to the Django API.")
    st.code(str(error))
    st.stop()

st.subheader("Search Products")

search = st.text_input("Search by product name or brand")
category = st.selectbox(
    "Filter by category",
    ["All", "electronics", "jewelery", "men's clothing", "women's clothing"]
)

params = {}

if search:
    params["search"] = search

if category != "All":
    params["category"] = category

try:
    response = requests.get(
        f"{API_BASE}/products/",
        params=params,
        timeout=10
    )
    response.raise_for_status()

    products = response.json()["products"]

    st.write(f"Found {len(products)} products")

    if products:
        st.dataframe(
            pd.DataFrame(products),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No products match your search.")

except requests.RequestException as error:
    st.error("Unable to load products.")
    st.code(str(error))


st.divider()
st.subheader("Marketplace Price Comparison")

try:
    response = requests.get(
        f"{API_BASE}/compare/",
        timeout=10
    )
    response.raise_for_status()

    comparisons = response.json()["comparisons"]

    if comparisons:
        comparison_df = pd.DataFrame(comparisons)

        st.dataframe(
            comparison_df,
            use_container_width=True,
            hide_index=True
        )

        if "source" in comparison_df.columns and "price" in comparison_df.columns:
            st.subheader("Latest Prices by Marketplace")

            source_prices = (
                comparison_df.groupby("source", as_index=False)["price"]
                .mean()
                .sort_values("price")
            )

            st.bar_chart(
                source_prices,
                x="source",
                y="price"
            )
    else:
        st.info("No marketplace price data is available yet.")

except requests.RequestException as error:
    st.error("Unable to load marketplace comparisons.")
    st.code(str(error))
