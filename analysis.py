import sqlite3
import pandas as pd
import matplotlib.pyplot as plt

# Load data
def load_data():
    conn = sqlite3.connect("prices.db")
    df = pd.read_sql_query("SELECT * FROM prices", conn)
    conn.close()
    return df

df = load_data()

print("\n--- OPTIONS ---")
print("1. Analyze Single Product")
print("2. Compare Two Products")

choice = input("Enter choice: ")

# OPTION 1: SINGLE PRODUCT

if choice == "1":
    product_type = input("Enter product type (crypto / book): ").lower()
    product_name = input("Enter product name: ")

    if product_type == "crypto":
        source = "API"
    elif product_type == "book":
        source = "SCRAPER"
    else:
        print("Invalid type")
        exit()

    df_filtered = df[(df["product_name"] == product_name) & (df["source"] == source)]

    if df_filtered.empty:
        print("❌ No data found")
        exit()

    df_filtered["timestamp"] = pd.to_datetime(df_filtered["timestamp"])
    df_filtered = df_filtered.sort_values("timestamp")

    # Moving average
    df_filtered["moving_avg"] = df_filtered["price"].rolling(window=3).mean()

    # 📊 Plot
    plt.figure()
    plt.plot(df_filtered["timestamp"], df_filtered["price"], label="Price")
    plt.plot(df_filtered["timestamp"], df_filtered["moving_avg"], label="Moving Avg")

    plt.xlabel("Time")
    plt.ylabel("Price")
    plt.title(product_name)

    plt.legend()
    plt.savefig("price_graph.png")
    plt.show()

    # 📊 Stats
    print("\n📊 STATISTICS")
    print("-------------------")
    print("Average:", df_filtered["price"].mean())
    print("Max:", df_filtered["price"].max())
    print("Min:", df_filtered["price"].min())
    print("Std Dev:", df_filtered["price"].std())

    # 📉 Trend
    if df_filtered["price"].iloc[-1] > df_filtered["price"].iloc[0]:
        print("📈 Trend: Increasing")
    elif df_filtered["price"].iloc[-1] < df_filtered["price"].iloc[0]:
        print("📉 Trend: Decreasing")
    else:
        print("➡️ Trend: Stable")

    # 🚨 Anomaly Detection
    mean = df_filtered["price"].mean()
    std = df_filtered["price"].std()

    df_filtered["z_score"] = (df_filtered["price"] - mean) / std
    anomalies = df_filtered[df_filtered["z_score"].abs() > 2]

    print("\n🚨 Anomalies:")
    print(anomalies[["price", "timestamp"]])

    # 🚨 Alert
    threshold = float(input("\nEnter price threshold: "))
    latest_price = df_filtered["price"].iloc[-1]

    if latest_price < threshold:
        print("🔥 ALERT: Price below threshold!")
    else:
        print("❌ Price still high")

    # 🧠 Decision Support
    avg_price = df_filtered["price"].mean()

    print("\n🧠 Decision Suggestion:")
    if latest_price < avg_price:
        print("✅ BUY NOW")
    else:
        print("⏳ WAIT")

    # 📁 Export
    df_filtered.to_csv("price_data.csv", index=False)
    print("📁 Data exported to price_data.csv")


# =========================
# 🔹 OPTION 2: COMPARISON
# =========================
elif choice == "2":
    product_type = input("Enter product type (crypto / book): ").lower()

    if product_type == "crypto":
        source = "API"
    elif product_type == "book":
        source = "SCRAPER"
    else:
        print("Invalid type")
        exit()

    product1 = input("Enter first product name: ")
    product2 = input("Enter second product name: ")

    df1 = df[(df["product_name"] == product1) & (df["source"] == source)]
    df2 = df[(df["product_name"] == product2) & (df["source"] == source)]

    if df1.empty or df2.empty:
        print("❌ Data not found for one or both products")
        exit()

    df1["timestamp"] = pd.to_datetime(df1["timestamp"])
    df2["timestamp"] = pd.to_datetime(df2["timestamp"])

    df1 = df1.sort_values("timestamp")
    df2 = df2.sort_values("timestamp")

    # 📊 Plot comparison
    plt.figure()
    plt.plot(df1["timestamp"], df1["price"], label=product1)
    plt.plot(df2["timestamp"], df2["price"], label=product2)

    plt.xlabel("Time")
    plt.ylabel("Price")
    plt.title("Comparison")

    plt.legend()
    plt.show()

    # 📊 Comparison stats
    avg1 = df1["price"].mean()
    avg2 = df2["price"].mean()

    print(f"\nAverage {product1}: {avg1}")
    print(f"Average {product2}: {avg2}")

    if avg1 < avg2:
        print(f"✅ {product1} is cheaper on average")
    else:
        print(f"✅ {product2} is cheaper on average")

else:
    print("Invalid choice")