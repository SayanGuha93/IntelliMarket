import sqlite3
import pandas as pd

# Connect database
conn = sqlite3.connect("prices.db")

# Load unified products table
df = pd.read_sql_query(
    "SELECT * FROM products",
    conn
)

print("\n🚀 ADVANCED ANALYTICS ENGINE\n")

# =========================================
# TOTAL PRODUCTS
# =========================================

print("📦 Total Products:", len(df))

# =========================================
# MOST EXPENSIVE PRODUCTS
# =========================================

print("\n💰 TOP 10 MOST EXPENSIVE PRODUCTS:\n")

expensive = df.sort_values(
    by="price",
    ascending=False
)

print(
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

print("\n🛒 TOP 10 CHEAPEST PRODUCTS:\n")

cheap = df.sort_values(by="price")

print(
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
# SOURCE ANALYSIS
# =========================================

print("\n📊 AVERAGE PRICE BY SOURCE:\n")

print(
    df.groupby("source")["price"]
    .mean()
    .sort_values(ascending=False)
)

# =========================================
# BRAND ANALYSIS
# =========================================

print("\n🏷️ TOP BRANDS:\n")

if "brand" in df.columns:

    print(
        df["brand"]
        .value_counts()
        .head(10)
    )

# =========================================
# CATEGORY ANALYSIS
# =========================================

print("\n🛍️ TOP CATEGORIES:\n")

if "category" in df.columns:

    print(
        df["category"]
        .value_counts()
        .head(10)
    )

# =========================================
# PRICE STATISTICS
# =========================================

print("\n📈 PRICE STATISTICS:\n")

print(df["price"].describe())

# =========================================
# BUSINESS INSIGHTS
# =========================================

print("\n🧠 BUSINESS INSIGHTS:\n")

avg_price = df["price"].mean()

print(f"Average Market Price: ₹{avg_price:.2f}")

highest = df.loc[df["price"].idxmax()]
lowest = df.loc[df["price"].idxmin()]

print("\n🔥 Highest Value Product:")
print(highest["product_name"])

print("\n🛒 Lowest Value Product:")
print(lowest["product_name"])

# Close connection
conn.close()