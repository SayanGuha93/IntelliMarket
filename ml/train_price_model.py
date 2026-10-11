
import sqlite3
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
import joblib


# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "prices.db"
MODEL_DIR = BASE_DIR / "models"
MODEL_PATH = MODEL_DIR / "price_model.pkl"


def load_price_data():
    """Read historical prices without modifying the database."""
    connection = sqlite3.connect(
        f"{DB_PATH.as_uri()}?mode=ro",
        uri=True
    )

    try:
        query = """
            SELECT
                pl.listing_id,
                p.product_name,
                ph.price,
                ph.recorded_at
            FROM price_history ph
            JOIN product_listings pl
                ON ph.listing_id = pl.listing_id
            JOIN products p
                ON pl.product_id = p.product_id
            WHERE ph.price IS NOT NULL
            ORDER BY pl.listing_id, ph.recorded_at
        """

        df = pd.read_sql_query(query, connection)
    finally:
        connection.close()

    df["recorded_at"] = pd.to_datetime(
        df["recorded_at"], errors="coerce", utc=True
    )
    df = df.dropna(subset=["recorded_at", "price"])
    return df


def prepare_features(df):
    """Use previous observations to predict the next price."""
    frames = []

    for listing_id, group in df.groupby("listing_id"):
        group = group.sort_values("recorded_at").copy()

        # Do not create artificial samples from duplicate timestamps.
        group = group.drop_duplicates(
            subset=["recorded_at"], keep="last"
        )

        group["lag_1"] = group["price"].shift(1)
        group["lag_2"] = group["price"].shift(2)
        group["rolling_mean_3"] = (
            group["price"].shift(1).rolling(3).mean()
        )
        group["day_number"] = (
            group["recorded_at"] - group["recorded_at"].min()
        ).dt.total_seconds() / 86400

        frames.append(group)

    data = pd.concat(frames, ignore_index=True)

    return data.dropna(
        subset=["lag_1", "lag_2", "rolling_mean_3"]
    )


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return

    df = load_price_data()

    if df.empty:
        print("No historical price data found.")
        return

    print("Total observations:", len(df))
    print("Listings:", df["listing_id"].nunique())
    print(
        "Listings with changing prices:",
        df.groupby("listing_id")["price"].nunique().gt(1).sum()
    )

    # A forecasting model needs actual price changes to learn
    # meaningful price movement.
    if df.groupby("listing_id")["price"].nunique().gt(1).sum() == 0:
        print("\nTraining stopped: prices are constant for every listing.")
        print("Collect genuine changing prices before training.")
        print("Baseline: the latest observed price per listing.")
        return

    data = prepare_features(df)

    features = [
        "lag_1",
        "lag_2",
        "rolling_mean_3",
        "day_number",
    ]

    # Split chronologically, not randomly.
    data = data.sort_values("recorded_at")
    split = int(len(data) * 0.8)

    if split == 0 or len(data) - split == 0:
        print("Not enough feature rows for a train/test split.")
        return

    train = data.iloc[:split]
    test = data.iloc[split:]

    model = RandomForestRegressor(
        n_estimators=200,
        random_state=42,
        min_samples_leaf=2
    )

    model.fit(train[features], train["price"])

    predictions = model.predict(test[features])
    mae = mean_absolute_error(test["price"], predictions)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": model, "features": features},
        MODEL_PATH
    )

    print("\nModel trained successfully.")
    print(f"Test MAE: {mae:.2f}")
    print(f"Saved model: {MODEL_PATH}")


if __name__ == "__main__":
    main()
