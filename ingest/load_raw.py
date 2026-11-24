"""Load the Olist CSVs into DuckDB schema `raw` and run basic data-quality checks."""

import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "warehouse.duckdb"

# table -> (csv file, primary key columns, expected rows per the Kaggle dataset card)
TABLES = {
    "customers": ("olist_customers_dataset.csv", ["customer_id"], 99_441),
    "geolocation": ("olist_geolocation_dataset.csv", None, 1_000_163),
    "order_items": ("olist_order_items_dataset.csv", ["order_id", "order_item_id"], 112_650),
    "order_payments": ("olist_order_payments_dataset.csv", ["order_id", "payment_sequential"], 103_886),
    "order_reviews": ("olist_order_reviews_dataset.csv", None, 99_224),  # review_id repeats in source; deduped in dbt
    "orders": ("olist_orders_dataset.csv", ["order_id"], 99_441),
    "products": ("olist_products_dataset.csv", ["product_id"], 32_951),
    "sellers": ("olist_sellers_dataset.csv", ["seller_id"], 3_095),
    "category_translation": ("product_category_name_translation.csv", ["product_category_name"], 71),
}


def load(con, raw_dir=RAW_DIR):
    con.execute("create schema if not exists raw")
    for table, (file, _, _) in TABLES.items():
        path = (raw_dir / file).as_posix()
        con.execute(f"create or replace table raw.{table} as select * from read_csv('{path}', header=true)")


def check(con, expect_counts=True):
    """Return a list of failure messages; empty means all checks passed."""
    failures = []
    for table, (_, key, expected) in TABLES.items():
        n = con.execute(f"select count(*) from raw.{table}").fetchall()[0][0]
        if expect_counts and n != expected:
            failures.append(f"{table}: {n} rows, expected {expected}")
        if key:
            cols = ", ".join(key)
            nulls = " or ".join(f"{c} is null" for c in key)
            dupes = con.execute(
                f"select count(*) from (select {cols} from raw.{table} group by {cols} having count(*) > 1)"
            ).fetchall()[0][0]
            null_keys = con.execute(f"select count(*) from raw.{table} where {nulls}").fetchall()[0][0]
            if dupes:
                failures.append(f"{table}: {dupes} duplicate keys on ({cols})")
            if null_keys:
                failures.append(f"{table}: {null_keys} null keys on ({cols})")
    orphans = con.execute(
        "select count(*) from raw.order_items i anti join raw.orders o using (order_id)"
    ).fetchall()[0][0]
    if orphans:
        failures.append(f"order_items: {orphans} rows with no matching order")
    return failures


def run(raw_dir=RAW_DIR, db_path=DB_PATH, expect_counts=True):
    """Load and check; raises if files are missing or any check fails."""
    missing = [f for f, _, _ in TABLES.values() if not (Path(raw_dir) / f).exists()]
    if missing:
        raise FileNotFoundError(f"Missing files in {raw_dir}: {missing}")
    with duckdb.connect(str(db_path)) as con:
        load(con, Path(raw_dir))
        failures = check(con, expect_counts)
    if failures:
        raise ValueError("ingest checks failed: " + "; ".join(failures))
    print(f"ingest ok: {raw_dir} -> {db_path}")


if __name__ == "__main__":
    try:
        run()
    except (FileNotFoundError, ValueError) as e:
        sys.exit(str(e))
