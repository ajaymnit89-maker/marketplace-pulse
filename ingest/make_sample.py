"""Cut a small, self-consistent sample of the Olist data for CI: 1,000 orders and every row they reference.

The full dataset stays out of git. Run once after downloading it; the output is committed under tests/fixtures/.
"""

from pathlib import Path

import duckdb

from ingest.load_raw import RAW_DIR, TABLES

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "olist_sample"
N_ORDERS = 1000


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    for table, (file, _, _) in TABLES.items():
        con.execute(f"create view {table} as select * from read_csv('{(RAW_DIR / file).as_posix()}', header=true)")

    # md5 order gives a stable pseudo-random spread across the whole date range
    con.execute(f"create table s_orders as select * from orders order by md5(order_id) limit {N_ORDERS}")
    con.execute("create table s_items as select * from order_items where order_id in (select order_id from s_orders)")
    queries = {
        "orders": "select * from s_orders",
        "order_items": "select * from s_items",
        "order_payments": "select * from order_payments where order_id in (select order_id from s_orders)",
        "order_reviews": "select * from order_reviews where order_id in (select order_id from s_orders)",
        "customers": "select * from customers where customer_id in (select customer_id from s_orders)",
        "sellers": "select * from sellers where seller_id in (select seller_id from s_items)",
        "products": "select * from products where product_id in (select product_id from s_items)",
        "category_translation": "select * from category_translation",
        "geolocation": """
            select * exclude (rn) from (
                select *, row_number() over (partition by geolocation_zip_code_prefix) as rn from geolocation
                where geolocation_zip_code_prefix in (
                    select customer_zip_code_prefix from customers where customer_id in (select customer_id from s_orders)
                    union select seller_zip_code_prefix from sellers where seller_id in (select seller_id from s_items)))
            where rn <= 3""",
    }
    for table, q in queries.items():
        path = (OUT / TABLES[table][0]).as_posix()
        con.execute(f"copy ({q}) to '{path}' (header, delimiter ',')")
        print(f"{table:22} {con.execute(f'select count(*) from ({q})').fetchall()[0][0]:>6} rows")


if __name__ == "__main__":
    main()
