import duckdb

from ingest.load_raw import TABLES, check, load


def write_fixture(raw_dir, dup_order=False):
    """One tiny CSV per table with the key columns only."""
    for table, (file, key, _) in TABLES.items():
        cols = key or ["id"]
        rows = [",".join(cols), ",".join("1" for _ in cols)]
        if table == "orders" and dup_order:
            rows.append("1")
        (raw_dir / file).write_text("\n".join(rows) + "\n")


def test_clean_data_passes(tmp_path):
    write_fixture(tmp_path)
    con = duckdb.connect()
    load(con, tmp_path)
    assert check(con, expect_counts=False) == []


def test_duplicate_key_is_caught(tmp_path):
    write_fixture(tmp_path, dup_order=True)
    con = duckdb.connect()
    load(con, tmp_path)
    assert any("orders: 1 duplicate keys" in f for f in check(con, expect_counts=False))
