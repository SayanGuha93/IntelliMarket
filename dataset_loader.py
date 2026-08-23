import pandas as pd
import sqlite3

# Connect database
conn = sqlite3.connect("prices.db")

# =========================================
# FLIPKART DATASET
# =========================================

flipkart = pd.read_csv("flipkart.csv")

flipkart = flipkart[[
    "product_name",
    "retail_price",
    "brand",
    "product_category_tree"
]]

flipkart.columns = [
    "product_name",
    "price",
    "brand",
    "category"
]

flipkart["source"] = "FLIPKART"

flipkart.dropna(inplace=True)

# =========================================
# MYNTRA DATASET
# =========================================

myntra = pd.read_csv("myntra.csv")

myntra = myntra[[
    "name",
    "price",
    "brand",
    "colour"
]]

myntra.columns = [
    "product_name",
    "price",
    "brand",
    "category"
]

myntra["source"] = "MYNTRA"

myntra.dropna(inplace=True)

# =========================================
# BOOKS DATA
# =========================================

try:
    books = pd.read_sql_query(
        """
        SELECT
            product_name,
            price,
            'BOOK' as brand,
            'Books' as category,
            source
        FROM prices
        WHERE source='SCRAPER'
        """,
        conn
    )

except:
    books = pd.DataFrame()

# =========================================
# CRYPTO DATA
# =========================================

try:
    crypto = pd.read_sql_query(
        """
        SELECT
            product_name,
            price,
            'CRYPTO' as brand,
            'Crypto' as category,
            source
        FROM prices
        WHERE source='API'
        """,
        conn
    )

except:
    crypto = pd.DataFrame()

# =========================================
# COMBINE EVERYTHING
# =========================================

combined = pd.concat(
    [flipkart, myntra, books, crypto],
    ignore_index=True
)

# Remove null values
combined.dropna(inplace=True)

# Save final unified table
combined.to_sql(
    "products",
    conn,
    if_exists="replace",
    index=False
)

print("\n✅ ALL DATA SOURCES INTEGRATED")
print(f"Total Products: {len(combined)}")

conn.close()