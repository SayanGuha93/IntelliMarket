"""Train an IntelliMarket next-observation price model from a CSV.

Required CSV columns: listing_id, product_id, product_name, source,
recorded_at, price, currency.
Reads CSV only; does not modify prices.db or existing ingestion code.
"""
from pathlib import Path
import json
import sys
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "price_history.csv"
ARTIFACT_DIR = ROOT / "ml" / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "price_model.joblib"
METADATA_PATH = ARTIFACT_DIR / "price_model_metadata.json"
REQUIRED = {"listing_id", "product_id", "product_name", "source", "recorded_at", "price", "currency"}
CAT = ["listing_id", "product_id", "source", "currency"]
NUM = ["lag_1", "lag_2", "rolling_mean_3", "last_change", "day_of_week", "month"]
FEATURES = CAT + NUM


def load_csv():
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"CSV not found: {CSV_PATH}\nCopy the template to data/price_history.csv and fill it with genuine observations."
        )
    df = pd.read_csv(CSV_PATH)
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError("Missing CSV columns: " + ", ".join(sorted(missing)))
    df = df.copy()
    df["recorded_at"] = pd.to_datetime(df["recorded_at"], errors="coerce", utc=True)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    for col in ["listing_id", "product_id", "product_name", "source", "currency"]:
        df[col] = df[col].astype("string").str.strip()
    df = df.dropna(subset=["listing_id", "product_id", "source", "currency", "recorded_at", "price"])
    df = df[(df["listing_id"] != "") & (df["product_id"] != "") & (df["source"] != "") & (df["currency"] != "") & (df["price"] >= 0)]
    df = df.drop_duplicates(subset=["listing_id", "recorded_at"], keep="first")
    df = df.sort_values(["listing_id", "recorded_at"]).reset_index(drop=True)
    if df.empty:
        raise ValueError("No valid observations found in the CSV.")
    return df


def make_supervised(df):
    parts = []
    for _, group in df.groupby("listing_id", sort=False):
        g = group.sort_values("recorded_at").copy()
        g["lag_1"] = g["price"].shift(1)
        g["lag_2"] = g["price"].shift(2)
        g["rolling_mean_3"] = g["price"].shift(1).rolling(3, min_periods=3).mean()
        g["last_change"] = g["lag_1"] - g["lag_2"]
        g["day_of_week"] = g["recorded_at"].dt.dayofweek
        g["month"] = g["recorded_at"].dt.month
        g["target_price"] = g["price"]
        g["target_time"] = g["recorded_at"]
        g = g.dropna(subset=["lag_1", "lag_2", "rolling_mean_3", "target_price"])
        if not g.empty:
            parts.append(g)
    if not parts:
        raise ValueError("Each listing needs at least 4 valid observations to create lag features.")
    return pd.concat(parts, ignore_index=True).sort_values("target_time").reset_index(drop=True)


def main():
    try:
        df = load_csv()
        data = make_supervised(df)
    except (FileNotFoundError, ValueError, pd.errors.ParserError) as exc:
        print(f"Training stopped: {exc}")
        return 1

    changed = int(df.groupby("listing_id")["price"].nunique().gt(1).sum())
    print("\nINTELLIMARKET CSV PRICE MODEL")
    print("-" * 42)
    print(f"Valid observations: {len(df)}")
    print(f"Listings: {df['listing_id'].nunique()}")
    print(f"Supervised examples: {len(data)}")
    print(f"Listings with actual price changes: {changed}")
    if data["target_price"].nunique() < 2 or changed == 0:
        print("\nTraining stopped: no genuine price variation found. Add real observations; do not invent prices.")
        return 1

    times = np.array(sorted(data["target_time"].unique()))
    if len(times) < 2:
        print("Training stopped: observations must span multiple timestamps.")
        return 1
    split_idx = min(max(int(len(times) * 0.8), 1), len(times) - 1)
    cutoff = pd.Timestamp(times[split_idx])
    train = data[data["target_time"] < cutoff].copy()
    test = data[data["target_time"] >= cutoff].copy()
    if len(train) < 10 or len(test) < 2:
        print(f"Training stopped: chronological split too small (train={len(train)}, test={len(test)}). Collect more real observations across dates.")
        return 1
    if train["target_price"].nunique() < 2:
        print("Training stopped: training period has no price variation.")
        return 1

    prep = ColumnTransformer([
        ("categorical", OneHotEncoder(handle_unknown="ignore"), CAT),
        ("numeric", "passthrough", NUM),
    ])
    model = Pipeline([
        ("preprocessor", prep),
        ("regressor", RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=42, n_jobs=-1)),
    ])
    model.fit(train[FEATURES], train["target_price"])
    pred = model.predict(test[FEATURES])
    baseline = test["lag_1"].to_numpy()
    mae = float(mean_absolute_error(test["target_price"], pred))
    baseline_mae = float(mean_absolute_error(test["target_price"], baseline))
    rmse = float(np.sqrt(mean_squared_error(test["target_price"], pred)))
    baseline_rmse = float(np.sqrt(mean_squared_error(test["target_price"], baseline)))

    print(f"Training examples: {len(train)}")
    print(f"Test examples: {len(test)}")
    print(f"Test period starts (UTC): {cutoff}")
    print("\n--- Chronological test results ---")
    print(f"Random Forest MAE : {mae:.4f}")
    print(f"Last-price MAE    : {baseline_mae:.4f}")
    print(f"Random Forest RMSE: {rmse:.4f}")
    print(f"Last-price RMSE   : {baseline_rmse:.4f}")
    print("\nRandom Forest beat baseline MAE." if mae < baseline_mae else "\nRandom Forest did not beat baseline MAE; do not assume it is better.")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    metadata = {
        "model_type": "RandomForestRegressor",
        "target": "next recorded price for a listing",
        "features": FEATURES,
        "train_examples": int(len(train)),
        "test_examples": int(len(test)),
        "test_period_start_utc": cutoff.isoformat(),
        "model_mae": mae,
        "baseline_mae": baseline_mae,
        "model_rmse": rmse,
        "baseline_rmse": baseline_rmse,
        "note": "Prices remain in source currency; do not mix currencies without conversion. Forecast quality depends on genuine observations and test results."
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"\nSaved model: {MODEL_PATH}")
    print(f"Saved metadata: {METADATA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
