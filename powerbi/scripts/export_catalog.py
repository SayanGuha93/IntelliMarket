"""Export the IntelliMarket snapshot for Power BI using only the standard library."""
import argparse
import csv
import json
from contextlib import ExitStack, closing
from decimal import Decimal
from pathlib import Path
import sqlite3
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT.parent / "rag_chatbot" / "artifacts" / "catalog.sqlite3"
DATA = ROOT / "data"
BANDS = (
    (0, "Unrecorded", None),
    (1, "Below 500", 50000),
    (2, "500 to below 1,000", 100000),
    (3, "1,000 to below 1,500", 150000),
    (4, "1,500 to below 3,000", 300000),
    (5, "3,000 and above", None),
)


def connect(path):
    return sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=ro", uri=True)


def write_csv(path, header, rows):
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header.split())
        writer.writerows(rows)


def amount(minor):
    return None if minor is None else Decimal(minor).scaleb(-2)


def discounts(field, retail, recorded):
    if field != "discounted_price" or retail is None or recorded is None or not 0 <= recorded <= retail or retail == 0:
        return None, None
    saving = retail - recorded
    return amount(saving), Decimal(saving) / Decimal(retail)


def band_key(minor):
    if minor is None:
        return 0
    return next(key for key, _, limit in BANDS[1:] if limit is None or minor < limit)


def export(catalog, output):
    output = output.resolve()
    if not output.is_relative_to(DATA.resolve()):
        raise ValueError("Export destination must be inside powerbi/data")
    with closing(connect(catalog)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        metadata = json.loads(db.execute("SELECT value FROM build_metadata WHERE name='ingestion'").fetchone()[0])
        if metadata["price_scale"] != 100 or metadata["currency"] is not None:
            raise ValueError("Catalog price metadata differs from the export contract")
        brand_keys = {}
        brands = [(0, None, "Unrecorded")]
        for key, label in db.execute("SELECT brand_key, MIN(brand) FROM products WHERE brand IS NOT NULL AND trim(brand_key) <> '' GROUP BY brand_key ORDER BY brand_key"):
            brand_keys[key] = len(brands)
            brands.append((brand_keys[key], key, label))
        categories = [(0, "Unrecorded", None, None, None, 0)]
        category_keys = {}
        facts = []
        for p in db.execute("SELECT * FROM products ORDER BY id"):
            brand_id = brand_keys.get(p["brand_key"], 0) if p["brand"] else 0
            path = json.loads(p["category_path"])
            key = (p["category_basis"], tuple(path))
            if path and key not in category_keys:
                category_keys[key] = len(categories)
                categories.append((category_keys[key], " > ".join(path), path[0], path[-1], p["category_basis"], len(path)))
            retail, recorded = p["retail_price_minor"], p["price_minor"]
            field = p["price_field"]
            if (p["platform"], field) not in {("myntra", "price"), ("flipkart", "discounted_price")}:
                raise ValueError("Unexpected marketplace price field")
            saving, ratio = discounts(field, retail, recorded)
            facts.append((
                p["id"], p["platform"], p["source_id"], p["name"], brand_id,
                category_keys.get(key, 0), band_key(recorded), p["colour"], field, amount(recorded),
                amount(retail), amount(recorded) if field == "discounted_price" else None, saving, ratio,
                p["rating"], p["overall_rating"], p["rating_count"], int(p["rating"] is not None),
                int(p["overall_rating"] is not None), int(p["rating_count"] is not None),
                int(recorded is None), int(retail is None), int(brand_id == 0), int(not path),
                int(not json.loads(p["attributes"])), int(p["colour"] is None), int(p["observed_at"] is None),
                int(bool(json.loads(p["conflicts"]))), p["observed_at"], p["product_url"], p["attributes"],
            ))
        lineage = list(db.execute("""
            SELECT platform || '.csv', platform, record_number, source_record_id, product_id,
                   status, reason, duplicate_of FROM source_records ORDER BY platform, record_number
        """))
    output.mkdir(parents=True, exist_ok=True)
    with ExitStack() as cleanup:
        staged = {}

        def stage(name, header, rows):
            # Sibling files inherit the destination ACL at creation on Windows.
            path = output / f".{name}.{uuid4().hex}.tmp"
            cleanup.callback(path.unlink, missing_ok=True)
            write_csv(path, header, rows)
            staged[name] = path

        stage("dim_marketplace", "marketplace marketplace_name", (("flipkart", "Flipkart"), ("myntra", "Myntra")))
        stage("dim_brand", "brand_id brand_key brand_name", brands)
        stage("dim_category", "category_id category_path top_category leaf_category category_basis category_depth", categories)
        stage("dim_price_band", "price_band_id price_band", ((key, label) for key, label, _ in BANDS))
        stage("fact_product", """
            product_id marketplace source_product_id product_name brand_id category_id price_band_id colour
            recorded_price_field recorded_price retail_price discounted_price discount_amount discount_fraction
            rating overall_rating rating_count has_rating has_overall_rating has_rating_count
            missing_recorded_price missing_retail_price missing_brand missing_category missing_attributes
            missing_colour missing_observation_date has_conflicts observed_at product_url attributes_json
        """, facts)
        stage("source_lineage", """
            source_file marketplace record_number source_record_id product_id status reason duplicate_of_record_number
        """, lineage)
        for name, path in staged.items():
            path.replace(output / f"{name}.csv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--output", type=Path, default=DATA)
    args = parser.parse_args()
    export(args.catalog, args.output)


if __name__ == "__main__":
    main()
