import streamlit as st
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt

# =========================================
# PAGE TITLE
# =========================================

st.title("🚀 Real-Time Price Analytics Dashboard")

# =========================================
# LOAD DATABASE
# =========================================

conn = sqlite3.connect("prices.db")

df = pd.read_sql_query(
    "SELECT * FROM products",
    conn
)

# =========================================
# BASIC INFO
# =========================================

st.header("📦 Database Overview")

st.write("Total Products:", len(df))

# =========================================
# =========================================
# PRODUCT ANALYTICS SEARCH
# =========================================

st.header("🔍 Product Intelligence Engine")

search = st.text_input("Enter product name")

if search:

    results = df[
        df["product_name"]
        .str.lower()
        .str.contains(search.lower(), na=False)
    ]

    # -------------------------------------
    # NO RESULTS
    # -------------------------------------

    if results.empty:

        st.error("❌ No products found")

    else:

        # ---------------------------------
        # SHOW PRODUCTS
        # ---------------------------------

        st.subheader("📦 Matching Products")

        st.dataframe(
            results[
                [
                    "product_name",
                    "price",
                    "brand",
                    "category",
                    "source"
                ]
            ].head(20)
        )

        # ---------------------------------
        # PRODUCT STATISTICS
        # ---------------------------------

        st.subheader("📈 Product Statistics")

        avg_price = results["price"].mean()
        max_price = results["price"].max()
        min_price = results["price"].min()

        st.write(f"💰 Average Price: ₹{avg_price:.2f}")
        st.write(f"🔥 Highest Price: ₹{max_price:.2f}")
        st.write(f"🛒 Lowest Price: ₹{min_price:.2f}")

        # ---------------------------------
        # SOURCE DISTRIBUTION
        # ---------------------------------

        st.subheader("📊 Source Analysis")

        source_counts = results["source"].value_counts()

        fig, ax = plt.subplots()

        ax.bar(
            source_counts.index,
            source_counts.values
        )

        ax.set_xlabel("Source")
        ax.set_ylabel("Products")

        st.pyplot(fig)

        # ---------------------------------
        # BRAND ANALYSIS
        # ---------------------------------

        if "brand" in results.columns:

            st.subheader("🏷️ Brand Analysis")

            brand_counts = (
                results["brand"]
                .value_counts()
                .head(10)
            )

            fig2, ax2 = plt.subplots()

            ax2.bar(
                brand_counts.index,
                brand_counts.values
            )

            ax2.set_xticklabels(
                brand_counts.index,
                rotation=45
            )

            st.pyplot(fig2)

        # ---------------------------------
        # PRICE TREND GRAPH
        # ---------------------------------

        st.subheader("📉 Price Distribution")

        fig3, ax3 = plt.subplots()

        ax3.plot(
            results["price"].values
        )

        ax3.set_xlabel("Products")
        ax3.set_ylabel("Price")

        st.pyplot(fig3)

        # ---------------------------------
        # DECISION SUPPORT
        # ---------------------------------

        st.subheader("🧠 Decision Support")

        if avg_price > 50000:
            st.warning(
                "This appears to be a premium/high-value product segment."
            )

        elif avg_price > 5000:
            st.info(
                "This product falls in the mid-range market segment."
            )

        else:
            st.success(
                "This product appears budget-friendly."
            )

# =========================================
# MOST EXPENSIVE PRODUCTS
# =========================================

st.header("💰 Top Expensive Products")

expensive = df.sort_values(
    by="price",
    ascending=False
)

st.dataframe(
    expensive[
        [
            "product_name",
            "price",
            "brand",
            "source"
        ]
    ].head(10)
)

# =========================================
# CHEAPEST PRODUCTS
# =========================================

st.header("🛒 Cheapest Products")

cheap = df.sort_values(by="price")

st.dataframe(
    cheap[
        [
            "product_name",
            "price",
            "brand",
            "source"
        ]
    ].head(10)
)

# =========================================
# SOURCE DISTRIBUTION
# =========================================

st.header("📊 Source Distribution")

source_counts = df["source"].value_counts()

fig, ax = plt.subplots()

ax.bar(
    source_counts.index,
    source_counts.values
)

ax.set_xlabel("Source")
ax.set_ylabel("Count")

st.pyplot(fig)

# =========================================
# CATEGORY DISTRIBUTION
# =========================================

if "category" in df.columns:

    st.header("🛍️ Category Distribution")

    category_counts = (
        df["category"]
        .value_counts()
        .head(10)
    )

    fig2, ax2 = plt.subplots()

    ax2.bar(
        category_counts.index,
        category_counts.values
    )

    ax2.set_xticklabels(
        category_counts.index,
        rotation=90
    )

    st.pyplot(fig2)

# =========================================
# PRICE STATISTICS
# =========================================

st.header("📈 Price Statistics")

st.write(df["price"].describe())

conn.close()