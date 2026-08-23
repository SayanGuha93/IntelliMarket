import sqlite3
import pandas as pd

# Connect database
conn = sqlite3.connect("prices.db")

# Load products table
df = pd.read_sql_query("SELECT * FROM products", conn)

print("\n🚀 PRODUCT SEARCH ENGINE STARTED")
print("Type 'exit' to stop\n")

# Infinite loop
while True:

    # User input
    search = input("Enter product name to search: ").lower()

    # Exit condition
    if search == "exit":
        print("\n✅ Search Engine Closed")
        break

    # Find matching products
    results = df[
        df["product_name"]
        .str.lower()
        .str.contains(search, na=False)
    ]

    # No results
    if results.empty:
        print("\n❌ No products found\n")

    else:
        print("\n✅ PRODUCTS FOUND:\n")

        # Display results
        print(
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

        print("\n" + "-" * 80 + "\n")

# Close database
conn.close()