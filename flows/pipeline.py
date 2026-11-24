"""End-to-end pipeline: raw CSVs -> DuckDB -> dbt marts -> ML outputs (-> AI review labels).

    python flows/pipeline.py              # full run on data/raw (ingest, dbt, 3 models)
    python flows/pipeline.py --with-ai    # also classify any new 1-2 star reviews (costs API credit)
    python flows/pipeline.py --sample     # CI: ingest + dbt on the committed 1,000-order sample, temp database
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

# Must precede the prefect import. No usage telemetry; and give the temporary local server time to create its
# database on a cold machine (CI), which can exceed the 20s default.
os.environ.setdefault("PREFECT_SERVER_ANALYTICS_ENABLED", "false")
os.environ.setdefault("PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS", "180")

from dbt.cli.main import dbtRunner
from prefect import flow, task

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # so `python flows/pipeline.py` can import the project packages

from ingest import load_raw

SAMPLE_DIR = ROOT / "tests" / "fixtures" / "olist_sample"


@task
def ingest(raw_dir, db_path, expect_counts):
    load_raw.run(raw_dir, db_path, expect_counts)


@task
def dbt_build(db_path):
    os.environ["DUCKDB_PATH"] = str(db_path)  # read by dbt/profiles.yml
    d = str(ROOT / "dbt")
    result = dbtRunner().invoke(["build", "--project-dir", d, "--profiles-dir", d])
    if not result.success:
        raise RuntimeError("dbt build failed")


@task
def train_late_model():
    from ml import late_delivery
    return late_delivery.main()


@task
def forecast():
    from ml import forecast
    return forecast.main()


@task
def segments():
    from ml import segments
    return segments.main()


@task
def classify_reviews():
    from ai import review_enrich
    review_enrich.main()


@flow(name="marketplace-pulse")
def pipeline(sample: bool = False, with_ai: bool = False):
    if sample:
        db = Path(tempfile.mkdtemp()) / "sample.duckdb"
        ingest(SAMPLE_DIR, db, expect_counts=False)
        dbt_build(db)
        return
    db = load_raw.DB_PATH
    ingest(load_raw.RAW_DIR, db, expect_counts=True)
    dbt_build(db)
    # Sequential on purpose: each step writes to the same DuckDB file, which allows one writer at a time.
    train_late_model()
    forecast()
    segments()
    if with_ai:
        classify_reviews()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="run ingest + dbt on the committed sample (CI)")
    ap.add_argument("--with-ai", action="store_true", help="also classify new reviews with Claude (paid)")
    args = ap.parse_args()
    pipeline(sample=args.sample, with_ai=args.with_ai)
