
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


# --------------------------------------------------
# 1. Paths and settings
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "Online Retail.xlsx"
OUTPUT_DIR = BASE_DIR / "ml"

MODEL_FILE = OUTPUT_DIR / "price_forecast_demo.joblib"
RESULTS_FILE = OUTPUT_DIR / "price_forecast_test_results.csv"
FORECAST_FILE = OUTPUT_DIR / "next_price_forecast.csv"

MAX_PRODUCTS = 80
RANDOM_STATE = 42

NUMERIC_FEATURES = [
    "current_price",
    "lag_1",
    "lag_2",
    "rolling_mean_3",
    "month",
    "day_of_week",
]
CATEGORICAL_FEATURES = ["StockCode"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


# --------------------------------------------------
# 2. Load and clean real transaction data
# --------------------------------------------------

def load_data():
    if not DATA_FILE.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATA_FILE}\n"
            "Download Online Retail.xlsx from the official "
            "UCI dataset page and place it in the data folder."
        )

    print("Loading the retail dataset...")
    df = pd.read_excel(DATA_FILE)

    required = {
        "InvoiceNo",
        "StockCode",
        "InvoiceDate",
        "Quantity",
        "UnitPrice",
    }
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df["InvoiceDate"] = pd.to_datetime(
        df["InvoiceDate"], errors="coerce"
    )
    df["UnitPrice"] = pd.to_numeric(
        df["UnitPrice"], errors="coerce"
    )
    df["Quantity"] = pd.to_numeric(
        df["Quantity"], errors="coerce"
    )
    df["StockCode"] = df["StockCode"].astype(str).str.strip()

    # Exclude cancelled invoices, returns and invalid prices.
    df = df[
        ~df["InvoiceNo"].astype(str).str.startswith("C")
        & (df["Quantity"] > 0)
        & (df["UnitPrice"] > 0)
        & df["InvoiceDate"].notna()
        & df["StockCode"].notna()
        & (df["StockCode"] != "")
    ].copy()

    # Aggregate transactions into one daily median price
    # per product. This reduces duplicate same-day sales.
    df["date"] = df["InvoiceDate"].dt.normalize()

    daily = (
        df.groupby(["StockCode", "date"], as_index=False)
        .agg(price=("UnitPrice", "median"))
        .sort_values(["StockCode", "date"])
        .reset_index(drop=True)
    )

    print(f"Clean daily product-price rows: {len(daily):,}")
    print(
        "Date range:",
        daily["date"].min().date(),
        "to",
        daily["date"].max().date(),
    )

    return daily


# --------------------------------------------------
# 3. Keep products with enough history and variation
# --------------------------------------------------

def select_products(daily):
    stats = daily.groupby("StockCode").agg(
        observations=("price", "size"),
        unique_prices=("price", "nunique"),
    )

    eligible = stats[
        (stats["observations"] >= 20)
        & (stats["unique_prices"] >= 2)
    ].sort_values("observations", ascending=False)

    selected = eligible.head(MAX_PRODUCTS).index

    if len(selected) < 2:
        raise ValueError(
            "Not enough products have 20+ daily observations "
            "and at least two distinct prices."
        )

    daily = daily[daily["StockCode"].isin(selected)].copy()
    print(f"Selected products: {len(selected)}")

    return daily


# --------------------------------------------------
# 4. Build lag features without using future prices
# --------------------------------------------------

def create_features(daily):
    daily = daily.sort_values(
        ["StockCode", "date"]
    ).copy()

    grouped = daily.groupby("StockCode", sort=False)["price"]

    # The features only use current or earlier observations.
    daily["current_price"] = daily["price"]
    daily["lag_1"] = grouped.shift(1)
    daily["lag_2"] = grouped.shift(2)

    daily["rolling_mean_3"] = grouped.transform(
        lambda s: s.rolling(window=3, min_periods=3).mean()
    )

    daily["month"] = daily["date"].dt.month
    daily["day_of_week"] = daily["date"].dt.dayofweek

    # Target: the next observed selling-day median price
    # for the same product.
    daily["target_price"] = grouped.shift(-1)
    daily["target_date"] = (
        daily.groupby("StockCode", sort=False)["date"].shift(-1)
    )

    return daily


# --------------------------------------------------
# 5. Train with a chronological split
# --------------------------------------------------

def train_model(features):
    usable = features.dropna(
        subset=FEATURES + ["target_price", "target_date"]
    ).copy()

    usable = usable.sort_values("target_date").reset_index(drop=True)

    if len(usable) < 100:
        raise ValueError(
            f"Only {len(usable)} training examples are available. "
            "More historical data is needed for this demo."
        )

    # Split by time, not randomly, to avoid training on future events.
    cutoff = usable["target_date"].quantile(0.80)

    train = usable[usable["target_date"] < cutoff].copy()
    test = usable[usable["target_date"] >= cutoff].copy()

    if train.empty or test.empty:
        raise ValueError("Chronological train/test split is empty.")

    preprocessing = ColumnTransformer(
        transformers=[
            (
                "product",
                OneHotEncoder(handle_unknown="ignore"),
                CATEGORICAL_FEATURES,
            ),
            ("numeric", "passthrough", NUMERIC_FEATURES),
        ]
    )

    model = Pipeline(
        steps=[
            ("preprocessing", preprocessing),
            (
                "regressor",
                RandomForestRegressor(
                    n_estimators=120,
                    min_samples_leaf=2,
                    random_state=RANDOM_STATE,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    model.fit(train[FEATURES], train["target_price"])
    predictions = model.predict(test[FEATURES])

    # Baseline: next observed price equals the current price.
    baseline_predictions = test["current_price"].to_numpy()

    model_mae = mean_absolute_error(
        test["target_price"], predictions
    )
    baseline_mae = mean_absolute_error(
        test["target_price"], baseline_predictions
    )

    print("\n--- IntelliMarket Forecast Demo ---")
    print(f"Training examples: {len(train):,}")
    print(f"Testing examples:  {len(test):,}")
    print(f"Test period begins: {cutoff.date()}")
    print(f"Model MAE:    £{model_mae:.4f}")
    print(f"Baseline MAE: £{baseline_mae:.4f}")

    if model_mae < baseline_mae:
        print("The model beats the baseline on this test period.")
    else:
        print("The model does not beat the baseline on this test period.")

    # Save actual vs predicted prices for inspection.
    results = test[
        ["StockCode", "date", "target_date", "current_price", "target_price"]
    ].copy()

    results = results.rename(
        columns={
            "date": "feature_date",
            "target_date": "forecast_target_date",
            "target_price": "actual_next_price",
        }
    )
    results["predicted_next_price"] = predictions
    results["baseline_next_price"] = baseline_predictions

    results.to_csv(RESULTS_FILE, index=False)
    joblib.dump(model, MODEL_FILE)

    print(f"\nSaved model: {MODEL_FILE}")
    print(f"Saved test results: {RESULTS_FILE}")

    return model, features


# --------------------------------------------------
# 6. Forecast the next observed price for one product
# --------------------------------------------------

def forecast_latest_product(model, features):
    candidates = features.dropna(
        subset=FEATURES
    ).sort_values(["StockCode", "date"])

    latest = candidates.groupby(
        "StockCode", sort=False
    ).tail(1).copy()

    if latest.empty:
        print("No product has enough history for a forecast.")
        return

    # Pick the product with the most historical observations.
    counts = features.groupby("StockCode").size()
    chosen_code = counts.idxmax()

    row = latest[latest["StockCode"] == chosen_code].tail(1)

    if row.empty:
        row = latest.tail(1)

    predicted_price = float(model.predict(row[FEATURES])[0])

    current_price = float(row["current_price"].iloc[0])
    last_date = row["date"].iloc[0]
    difference = predicted_price - current_price

    forecast = pd.DataFrame(
        [
            {
                "StockCode": row["StockCode"].iloc[0],
                "last_observed_date": last_date,
                "last_observed_price_GBP": current_price,
                "predicted_next_observed_price_GBP": predicted_price,
                "difference_GBP": difference,
                "model_note": (
                    "Experimental estimate of next observed "
                    "transaction price, not a live store price."
                ),
            }
        ]
    )

    forecast.to_csv(FORECAST_FILE, index=False)

    print("\n--- Example Forecast ---")
    print(f"Product code: {forecast['StockCode'].iloc[0]}")
    print(f"Last observed date: {last_date.date()}")
    print(f"Last observed median: £{current_price:.2f}")
    print(f"Estimated next observed price: £{predicted_price:.2f}")
    print(f"Estimated difference: £{difference:+.2f}")
    print(f"Saved forecast: {FORECAST_FILE}")


# --------------------------------------------------
# 7. Run the demonstration
# --------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    daily = load_data()
    daily = select_products(daily)
    features = create_features(daily)

    model, features = train_model(features)
    forecast_latest_product(model, features)


if __name__ == "__main__":
    main()
