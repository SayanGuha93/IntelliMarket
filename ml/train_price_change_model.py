
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.ensemble import RandomForestClassifier


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "price_changes_sample.csv"


def main():
    if not CSV_PATH.exists():
        print(f"CSV not found: {CSV_PATH}")
        return

    df = pd.read_csv(CSV_PATH)

    required = {
        "date",
        "change_type",
        "old_price",
        "new_price",
        "old_available",
        "new_available",
    }

    missing = required - set(df.columns)
    if missing:
        print(f"Missing columns: {sorted(missing)}")
        print(f"Available columns: {df.columns.tolist()}")
        return

    # Validate and clean real price observations.
    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
    df["old_price"] = pd.to_numeric(df["old_price"], errors="coerce")
    df["new_price"] = pd.to_numeric(df["new_price"], errors="coerce")

    df = df.dropna(
        subset=["date", "change_type", "old_price", "new_price"]
    ).copy()

    df = df[
        (df["old_price"] >= 0)
        & (df["new_price"] >= 0)
    ].copy()

    # The target is the observed event type.
    # Price amounts are used as input features to classify the event.
    df["price_difference"] = df["new_price"] - df["old_price"]
    df["percentage_change"] = (
        (df["new_price"] - df["old_price"])
        / df["old_price"].replace(0, float("nan"))
        * 100
    )
    df["event_month"] = df["date"].dt.month
    df["event_day_of_week"] = df["date"].dt.dayofweek

    # Remove rows whose target is missing.
    df = df.dropna(subset=["change_type"])

    if len(df) < 20:
        print(
            f"Only {len(df)} usable rows found. "
            "More real observations are recommended for evaluation."
        )
        if len(df) < 10:
            return

    print("\nINTELLIMARKET PRICE-CHANGE CLASSIFIER")
    print("-" * 45)
    print(f"Usable rows: {len(df)}")
    print("\nEvent distribution:")
    print(df["change_type"].value_counts().to_string())

    # Note: these features describe an already observed event.
    # This is an event-classification experiment, not a future forecast.
    feature_columns = [
        "old_price",
        "new_price",
        "price_difference",
        "percentage_change",
        "old_available",
        "new_available",
        "event_month",
        "event_day_of_week",
    ]

    X = df[feature_columns].copy()
    y = df["change_type"].astype(str)

    # Encode availability fields consistently.
    for col in ["old_available", "new_available"]:
        X[col] = X[col].astype("string").fillna("unknown")

    numeric_features = [
        "old_price",
        "new_price",
        "price_difference",
        "percentage_change",
        "event_month",
        "event_day_of_week",
    ]
    categorical_features = ["old_available", "new_available"]

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "numeric",
                SimpleImputer(strategy="median"),
                numeric_features,
            ),
            (
                "categorical",
                Pipeline(
                    steps=[
                        (
                            "imputer",
                            SimpleImputer(strategy="most_frequent"),
                        ),
                        (
                            "encoder",
                            OneHotEncoder(handle_unknown="ignore"),
                        ),
                    ]
                ),
                categorical_features,
            ),
        ]
    )

    # Use a stratified split when every class has enough examples.
    class_counts = y.value_counts()
    stratify = y if class_counts.min() >= 2 else None

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        random_state=42,
        stratify=stratify,
    )

    model = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            (
                "classifier",
                RandomForestClassifier(
                    n_estimators=200,
                    random_state=42,
                    class_weight="balanced",
                ),
            ),
        ]
    )

    model.fit(X_train, y_train)
    predictions = model.predict(X_test)

    print("\n--- Test Results ---")
    print(f"Accuracy: {accuracy_score(y_test, predictions):.4f}")
    print("\nClassification report:")
    print(
        classification_report(
            y_test,
            predictions,
            zero_division=0,
        )
    )
    print("Confusion matrix:")
    print(confusion_matrix(y_test, predictions))

    print(
        "\nImportant: this experiment classifies recorded event types "
        "using fields from those events. It does not predict future prices. "
        "For future forecasting, use earlier information only and evaluate "
        "on later dated observations."
    )


if __name__ == "__main__":
    main()
