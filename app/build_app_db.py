"""Export what the app and Power BI need, and nothing else.

- app/app.duckdb: the governed marts, ml and ai schemas only (no raw or staging data). Committed, so the
  deployed Streamlit app and the analyst agent work without the full warehouse.
- data/export/*.parquet: the same tables as Parquet files for Power BI.

Without the full warehouse (a fresh clone), it only writes the Parquet files, from the committed app.duckdb.
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
APP_DB = ROOT / "app" / "app.duckdb"
PARQUET_DIR = ROOT / "data" / "export"
SCHEMAS = ("marts", "ml", "ai")


def parquet_from_app_db():
    """Fresh clone without the warehouse: write the Power BI Parquet files from the committed app.duckdb."""
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(APP_DB), read_only=True)
    tables = con.execute("select schema_name, table_name from duckdb_tables()").fetchall()
    for schema, table in tables:
        con.execute(f"copy {schema}.{table} to '{(PARQUET_DIR / f'{schema}__{table}.parquet').as_posix()}' (format parquet)")
    print(f"{len(tables)} tables from {APP_DB.name} -> {PARQUET_DIR}")


def main():
    if not WAREHOUSE.exists():
        return parquet_from_app_db()
    APP_DB.unlink(missing_ok=True)
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(APP_DB))
    con.execute(f"attach '{WAREHOUSE.as_posix()}' as wh (read_only)")
    tables = con.execute(f"""select schema_name, table_name from duckdb_tables()
                             where database_name = 'wh' and schema_name in {SCHEMAS} order by 1, 2""").fetchall()
    for schema, table in tables:
        con.execute(f"create schema if not exists {schema}")
        con.execute(f"create table {schema}.{table} as select * from wh.{schema}.{table}")
        con.execute(f"copy {schema}.{table} to '{(PARQUET_DIR / f'{schema}__{table}.parquet').as_posix()}' (format parquet)")
    con.execute("detach wh")
    con.close()
    print(f"{len(tables)} tables -> {APP_DB.name} ({APP_DB.stat().st_size / 1e6:.1f} MB) and {PARQUET_DIR}")


if __name__ == "__main__":
    main()
