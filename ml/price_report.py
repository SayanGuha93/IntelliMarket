
import sqlite3
from pathlib import Path

import pandas as pd


# Locate prices.db from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "prices.db"


def load_price_history():
    """Read price history without modifying the database."""

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DATABASE_PATH}"
        )

    # Open the database in read-only mode.
    connection = sqlite3.connect(
        f"{DATABASE_PATH.as_uri()}?mode=ro",
        uri=True
    )

    try:
        query = """
            SELECT
                p.product_id,
                p.product_name,
                pl.listing_id,
                pl.source,
                ph.price,
                ph.recorded_at
            FROM price_history AS ph
            JOIN product_listings AS pl
                ON ph.listing_id = pl.listing_id
            JOIN products AS p
                ON pl.product_id = p.product_id
            WHERE ph.price IS NOT NULL
            ORDER BY ph.recorded_at ASC
        """

        df = pd.read_sql_query(query, connection)
    finally:
        connection.close()

    if df.empty:
        print("No price history found in the database.")
        return df

    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["recorded_at"] = pd.to_datetime(
        df["recorded_at"], errors="coerce", utc=True
    )

    df = df.dropna(subset=["price", "recorded_at"])
    return df


def create_price_report(df):
    """Display a summary and latest price for every listing."""

    if df.empty:
        return

    total_observations = len(df)
    total_products = df["product_id"].nunique()
    total_listings = df["listing_id"].nunique()

    print("\n" + "=" * 75)
    print("             INTELLIMARKET PRICE HISTORY REPORT")
    print("=" * 75)

    print(f"\nTotal observations : {total_observations}")
    print(f"Unique products    : {total_products}")
    print(f"Unique listings    : {total_listings}")
    print(
        "Date range         : "
        f"{df['recorded_at'].min()} to {df['recorded_at'].max()}"
    )

    # Summarize each individual marketplace listing.
    report = (
        df.groupby(
            ["listing_id", "product_id", "product_name", "source"],
            as_index=False
        )
        .agg(
            observations=("price", "count"),
            latest_price=("price", "last"),
            minimum_price=("price", "min"),
            maximum_price=("price", "max"),
            unique_prices=("price", "nunique"),
        )
    )

    report["price_change"] = (
        report["maximum_price"] - report["minimum_price"]
    )

    report["status"] = report["unique_prices"].apply(
        lambda count: (
            "Price changed"
            if count > 1
            else "No observed change"
        )
    )

    money_columns = [
        "latest_price",
        "minimum_price",
        "maximum_price",
        "price_change",
    ]

    for column in money_columns:
        report[column] = report[column].round(2)

    print("\n--- Listing-wise Price Summary ---\n")

    print(
        report[
            [
                "listing_id",
                "product_name",
                "source",
                "observations",
                "latest_price",
                "minimum_price",
                "maximum_price",
                "price_change",
                "status",
            ]
        ].to_string(index=False)
    )

    changed = int((report["unique_prices"] > 1).sum())
    unchanged = len(report) - changed

    print("\n--- Overall Price Movement ---")
    print(f"Listings with price changes : {changed}")
    print(f"Listings without changes    : {unchanged}")

    if changed == 0:
        print(
            "\nConclusion: No price movement was observed in the "
            "recorded data. A meaningful price forecasting model "
            "cannot be evaluated from these observations alone."
        )
    else:
        print(
            "\nConclusion: Some listings have different recorded "
            "prices. Check the observation dates and data quality "
            "before training a forecasting model."
        )

    # Save the report as a new CSV file.
    output_path = PROJECT_ROOT / "price_report.csv"
    report.to_csv(output_path, index=False)

    print(f"\nReport saved to: {output_path}")


def main():
    try:
        df = load_price_history()
        create_price_report(df)
    except (FileNotFoundError, sqlite3.Error) as error:
        print(f"Error: {error}")


if __name__ == "__main__":
    main()
