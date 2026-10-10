
import re
import sqlite3
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "prices.db"
OUTPUT_DIR = PROJECT_ROOT / "price_history_charts"


def load_price_history():
    """Load price history without modifying the database."""

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DATABASE_PATH}"
        )

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
        print("No price history available to plot.")
        return df

    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["recorded_at"] = pd.to_datetime(
        df["recorded_at"],
        errors="coerce",
        utc=True
    )

    df = df.dropna(subset=["price", "recorded_at"])
    return df


def plot_listing_history(df, listing_id, group):
    """Create and save a chart for one marketplace listing."""

    group = group.sort_values("recorded_at")

    product_name = str(group["product_name"].iloc[0])
    source = str(group["source"].iloc[0])

    fig, ax = plt.subplots(figsize=(10, 5))

    ax.plot(
        group["recorded_at"],
        group["price"],
        marker="o",
        linewidth=2,
        markersize=5,
        label="Recorded price"
    )

    ax.set_title(
        f"{product_name}\n"
        f"Source: {source} | Listing ID: {listing_id}"
    )
    ax.set_xlabel("Recorded date (UTC)")
    ax.set_ylabel("Price (source currency)")
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend()

    ax.xaxis.set_major_formatter(
        mdates.DateFormatter("%d %b", tz=mdates.UTC)
    )
    fig.autofmt_xdate()
    fig.tight_layout()

    # Create a safe filename for Windows.
    safe_name = re.sub(
        r'[<>:"/\\|?*]',
        "_",
        product_name
    )
    safe_name = safe_name[:70].strip(" ._")

    output_path = OUTPUT_DIR / (
        f"listing_{listing_id}_{safe_name}.png"
    )

    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved: {output_path.name}")


def main():
    try:
        df = load_price_history()

        if df.empty:
            return

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        print("\nINTELLIMARKET PRICE HISTORY VISUALIZATION")
        print("-" * 50)
        print(f"Total observations: {len(df)}")
        print(f"Unique listings: {df['listing_id'].nunique()}")
        print(f"Output folder: {OUTPUT_DIR}\n")

        for listing_id, group in df.groupby("listing_id"):
            plot_listing_history(df, listing_id, group)

        print("\nVisualization completed successfully.")
        print(f"Open this folder to view the charts:\n{OUTPUT_DIR}")

    except (FileNotFoundError, sqlite3.Error) as error:
        print(f"Database error: {error}")


if __name__ == "__main__":
    main()
