
import sqlite3
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "prices.db"

LAG_COUNT = 3
MIN_UNIQUE_PRICES = 5
MIN_TRAIN_SAMPLES = 10
MIN_TEST_SAMPLES = 2
TEST_FRACTION = 0.20


def load_price_history():
    """Read price history without modifying the database."""
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
                pl.listing_id,
                p.product_name,
                pl.source,
                ph.price,
                ph.recorded_at,
                ph.id AS history_id
            FROM price_history ph
            JOIN product_listings pl
                ON ph.listing_id = pl.listing_id
            JOIN products p
                ON pl.product_id = p.product_id
            ORDER BY
                pl.listing_id,
                ph.recorded_at,
                ph.id
        """
        return pd.read_sql_query(query, connection)
    finally:
        connection.close()


def create_event_series(history):
    """
    Collapse consecutive identical prices into price-change
    events. Keep the first observation and every subsequent
    observation whose price differs from the previous price.
    """
    history = history.sort_values(
        ["recorded_at", "history_id"]
    ).copy()

    changed = history["price"].ne(
        history["price"].shift(1)
    )

    return history.loc[changed, "price"].astype(float).tolist()


def make_features(prices):
    """Use previous price events to predict the next event."""
    data = pd.DataFrame({"price": prices})

    for lag in range(1, LAG_COUNT + 1):
        data[f"lag_{lag}"] = data["price"].shift(lag)

    data = data.dropna().reset_index(drop=True)

    columns = [
        f"lag_{lag}"
        for lag in range(1, LAG_COUNT + 1)
    ]

    return data[columns], data["price"], columns


def evaluate(name, model, X_train, y_train, X_test, y_test):
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)

    mae = mean_absolute_error(y_test, predictions)
    rmse = mean_squared_error(
        y_test, predictions
    ) ** 0.5

    print(f"\n{name}")
    print(f"  MAE:  {mae:.4f}")
    print(f"  RMSE: {rmse:.4f}")

    return model


def analyze_listing(listing_id, name, source, history):
    raw_prices = history["price"].astype(float)
    events = create_event_series(history)
    unique_raw_prices = raw_prices.nunique()

    print("\n" + "-" * 75)
    print(f"Listing: {listing_id} | {name}")
    print(f"Source: {source}")
    print(f"Raw records: {len(history)}")
    print(f"Distinct raw prices: {unique_raw_prices}")
    print(f"Price-change events: {len(events)}")

    if unique_raw_prices == 1:
        print(
            "STATUS: No observed price movement. "
            "Forecasting evaluation skipped."
        )
        print(
            f"Last observed price baseline: "
            f"{raw_prices.iloc[-1]:.2f}"
        )
        return

    if unique_raw_prices < MIN_UNIQUE_PRICES:
        print(
            "STATUS: Insufficient price variation. "
            f"At least {MIN_UNIQUE_PRICES} distinct prices "
            "are required for this experiment."
        )
        return

    X, y, feature_columns = make_features(events)

    split = int(len(X) * (1 - TEST_FRACTION))
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    if (
        len(X_train) < MIN_TRAIN_SAMPLES
        or len(X_test) < MIN_TEST_SAMPLES
    ):
        print(
            "STATUS: Price variation exists, but there are "
            "not enough samples for reliable chronological "
            "evaluation."
        )
        print(
            f"Training samples available: {len(X_train)} "
            f"(minimum {MIN_TRAIN_SAMPLES})"
        )
        print(
            f"Test samples available: {len(X_test)} "
            f"(minimum {MIN_TEST_SAMPLES})"
        )
        return

    print("STATUS: Eligible for experimental evaluation.")
    print(f"Training samples: {len(X_train)}")
    print(f"Test samples: {len(X_test)}")

    # Baseline: predict each test price using the latest
    # price known at that point in the sequence.
    baseline_predictions = X_test["lag_1"].to_numpy()

    print("\nLast-observed-price baseline")
    print(
        f"  MAE:  "
        f"{mean_absolute_error(y_test, baseline_predictions):.4f}"
    )
    print(
        f"  RMSE: "
        f"{mean_squared_error(y_test, baseline_predictions) ** 0.5:.4f}"
    )

    models = {
        "Linear Regression": LinearRegression(),
        "Random Forest": RandomForestRegressor(
            n_estimators=200,
            max_depth=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        )
    }

    for model_name, model in models.items():
        evaluate(
            model_name,
            model,
            X_train,
            y_train,
            X_test,
            y_test
        )

    print(
        "\nNote: metrics are experimental and reflect the "
        "available event history, not a guarantee of future accuracy."
    )


def main():
    history = load_price_history()

    if history.empty:
        print("No price history found.")
        return

    print("INTELLIMARKET PRICE FORECASTING DIAGNOSTICS")
    print("=" * 75)
    print(f"Database: {DATABASE_PATH}")
    print(f"Total raw records: {len(history)}")
    print(f"Listings: {history['listing_id'].nunique()}")
    print("Database opened in read-only mode.")

    for (listing_id, name, source), group in history.groupby(
        ["listing_id", "product_name", "source"],
        sort=True
    ):
        analyze_listing(
            listing_id,
            name,
            source,
            group
        )


if __name__ == "__main__":
    main()
