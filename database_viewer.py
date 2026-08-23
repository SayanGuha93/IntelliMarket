import sqlite3
import pandas as pd

# Connect database
conn = sqlite3.connect("prices.db")

# Load products table
df = pd.read_sql_query("SELECT * FROM products", conn)

# =========================================
# BASIC DATABASE INFO
# =========================================

print("\n🚀 DATABASE OVERVIEW\n")

print("Total Products:", len(df))

print("\nColumns:")
print(df.columns)

# =========================================
# SOURCE DISTRIBUTION
# =========================================

print("\n📦 PRODUCTS BY SOURCE:\n")
print(df["source"].value_counts())

# =========================================
# CATEGORY DISTRIBUTION
# =========================================

print("\n🛒 PRODUCTS BY CATEGORY:\n")

if "category" in df.columns:
    print(df["category"].value_counts().head(10))

# =========================================
# SAMPLE PRODUCTS
# =========================================

print("\n📝 SAMPLE PRODUCTS:\n")

print(
    df[
        [
            "product_name",
            "price",
            "brand",
            "source"
        ]
    ].head(20)
)

# =========================================
# PRICE STATISTICS
# =========================================

print("\n💰 PRICE STATISTICS:\n")

print(df["price"].describe())

# Close connection
conn.close()