"""Customer segments: KMeans on recency, frequency, spend, review score and late-delivery share.

k=5 was picked over k=3 (higher silhouette) because it separates customers unhappy for reasons other than lateness.
Segments are named from their profiles, not cluster ids, so names survive a data refresh. Writes ml.customer_segments.
"""

from pathlib import Path

import duckdb
import mlflow
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
SNAPSHOT = "2018-09-01"
K = 5


def name_segment(p, recency_cut):
    """p: one segment's profile (mean late_share, frequency, avg_review; median recency_days)."""
    if p.late_share > 0.5:
        return "Burned by late delivery"
    if p.frequency > 1.5:
        return "Repeat buyers"
    if p.avg_review < 3:
        return "Unhappy, delivered on time"
    return "Happy, lapsed" if p.recency_days > recency_cut else "Happy, recent"


def main():
    con = duckdb.connect(str(DB))
    df = con.sql(f"""
        select customer_unique_id,
               date_diff('day', max(purchase_date), date '{SNAPSHOT}') as recency_days,
               count(*) as frequency,
               sum(order_value) as monetary,
               avg(review_score) as avg_review,
               coalesce(avg(is_late::int), 0) as late_share
        from marts.fct_orders where not is_canceled
        group by 1 order by 1  -- fixed row order keeps KMeans reproducible
    """).df()
    df["avg_review"] = df.avg_review.fillna(df.avg_review.median())  # ~0.7% never left a review

    X = StandardScaler().fit_transform(np.column_stack([
        df.recency_days, np.log1p(df.frequency), np.log1p(df.monetary), df.avg_review, df.late_share,
    ]))
    df["cluster"] = KMeans(K, n_init=10, random_state=42).fit_predict(X)
    sample = np.random.default_rng(0).choice(len(X), 15000, replace=False)
    silhouette = silhouette_score(X[sample], df.cluster.to_numpy()[sample])

    prof = df.groupby("cluster").agg(late_share=("late_share", "mean"), frequency=("frequency", "mean"),
                                     avg_review=("avg_review", "mean"), recency_days=("recency_days", "median"))
    names = {c: name_segment(p, df.recency_days.median()) for c, p in prof.iterrows()}
    assert len(set(names.values())) == K, f"segment names collided: {names}"
    df["segment"] = df.cluster.map(names)

    summary = df.groupby("segment").agg(
        customers=("customer_unique_id", "size"), median_recency_days=("recency_days", "median"),
        avg_orders=("frequency", "mean"), median_spend=("monetary", "median"),
        avg_review=("avg_review", "mean"), late_share=("late_share", "mean"),
    ).round(2).sort_values("customers", ascending=False)
    print(f"silhouette {silhouette:.3f}\n{summary.to_string()}")

    out = df.drop(columns="cluster")  # noqa: F841
    con.execute("create schema if not exists ml")
    con.execute("create or replace table ml.customer_segments as select * from out")
    con.close()

    mlflow.set_tracking_uri(f"sqlite:///{(ROOT / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("marketplace-pulse")
    with mlflow.start_run(run_name="customer_segments"):
        mlflow.log_params({"k": K, "snapshot": SNAPSHOT})
        mlflow.log_metric("silhouette", silhouette)
    return summary


if __name__ == "__main__":
    main()
