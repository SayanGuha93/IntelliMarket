import sqlite3
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "prices.db"

connection = sqlite3.connect(
    f"{DB_PATH.as_uri()}?mode=ro",
    uri=True
)

try:
    query = """
        SELECT
            pl.listing_id,
            p.product_name,
            pl.source,
            ph.price,
            ph.recorded_at
        FROM price_history ph
        JOIN product_listings pl
            ON ph.listing_id = pl.listing_id
        JOIN products p
            ON pl.product_id = p.product_id
        ORDER BY pl.listing_id, ph.recorded_at
    """

    df = pd.read_sql_query(query, connection)
finally:
    connection.close()

if df.empty:
    print("No price history available.")
else:
    df["recorded_at"] = pd.to_datetime(
        df["recorded_at"], errors="coerce", utc=True
    )

    summary = df.groupby(
        ["listing_id", "product_name", "source"]
    ).agg(
        observations=("price", "count"),
        unique_prices=("price", "nunique"),
        first_record=("recorded_at", "min"),
        last_record=("recorded_at", "max"),
    ).reset_index()

    print("\nPRICE HISTORY SUMMARY")
    print(summary.to_string(index=False))

    print("\nTOTAL OBSERVATIONS:", len(df))
    print("UNIQUE LISTINGS:", df["listing_id"].nunique())
    print(
        "LISTINGS WITH PRICE CHANGES:",
        int((summary["unique_prices"] > 1).sum())
    )