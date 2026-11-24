"""Late-delivery risk model: train on orders before April 2018, test on April-July 2018, score every order.

Writes ml.order_late_risk to DuckDB, logs the run to MLflow, saves a SHAP driver chart to docs/img.
"""

from pathlib import Path

import duckdb
import lightgbm as lgb
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import shap
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
TRAIN_END, TEST_END = "2018-04-01", "2018-08-01"  # later orders are excluded: many were still in transit

CATEGORICAL = ["customer_state", "seller_state", "main_category", "main_payment_type"]
NUMERIC = [
    # purchase_month left out: it mostly memorised the one-off Feb-Mar 2018 spike and added ~0.005 PR-AUC
    "same_state", "distance_km", "promised_days", "purchase_dow", "purchase_hour",
    "days_to_ship_limit", "item_count", "seller_count", "order_value", "freight_value", "freight_ratio",
    "total_weight_g", "total_volume_cm3", "max_installments", "seller_prior_orders", "seller_prior_late_rate",
]
FEATURES = CATEGORICAL + NUMERIC
PARAMS = {"n_estimators": 400, "learning_rate": 0.03, "num_leaves": 31, "min_child_samples": 50,
              "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8, "random_state": 42, "verbose": -1}


def capture_at(y, score, frac=0.1):
    """Share of all positives that land in the top `frac` of scores."""
    y, score = np.asarray(y), np.asarray(score)
    top = np.argsort(-score)[: int(len(score) * frac)]
    return y[top].sum() / y.sum()


def main():
    con = duckdb.connect(str(DB))
    df = con.sql("select * from ml.ml_order_features order by order_id").df()  # fixed order: reproducible model
    for c in CATEGORICAL:
        df[c] = df[c].astype("category")
    df["same_state"] = df.same_state.astype(float)

    labeled = df[df.is_late.notna() & (df.purchased_at < TEST_END)]
    train = labeled[labeled.purchased_at < TRAIN_END]
    test = labeled[labeled.purchased_at >= TRAIN_END]
    y_train, y_test = train.is_late.astype(int), test.is_late.astype(int)

    model = lgb.LGBMClassifier(**PARAMS).fit(train[FEATURES], y_train)
    p_model = model.predict_proba(test[FEATURES])[:, 1]

    # Baseline: each customer state's historical late rate from the training period.
    state_rate = train.groupby("customer_state", observed=True).is_late.mean()
    p_base = test.customer_state.map(state_rate).astype(float).fillna(y_train.mean()).to_numpy()

    metrics = {
        "test_prevalence": y_test.mean(),
        "pr_auc_model": average_precision_score(y_test, p_model),
        "pr_auc_baseline": average_precision_score(y_test, p_base),
        "roc_auc_model": roc_auc_score(y_test, p_model),
        "roc_auc_baseline": roc_auc_score(y_test, p_base),
        "capture_top10_model": capture_at(y_test, p_model),
        "capture_top10_baseline": capture_at(y_test, p_base),
    }
    for k, v in metrics.items():
        print(f"{k:24} {v:.3f}")

    # What drives the score: mean |SHAP| on a test sample.
    sample = test[FEATURES].sample(5000, random_state=42)
    sv = shap.TreeExplainer(model).shap_values(sample)
    sv = sv[1] if isinstance(sv, list) else sv
    imp = (np.abs(sv).mean(axis=0)).round(4)
    order = np.argsort(imp)[-12:]
    fig, ax = plt.subplots(figsize=(7, 4.2), facecolor="#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ax.barh(np.array(FEATURES)[order], imp[order], color="#2a78d6", height=0.6)
    ax.set_title("What drives late-delivery risk (mean |SHAP|, test set)", loc="left", fontweight="bold")
    ax.set_xlabel("average impact on predicted log-odds", color="#52514e")
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.grid(axis="x", color="#e4e3df")
    ax.set_axisbelow(True)
    fig.tight_layout()
    chart = ROOT / "docs" / "img" / "late_model_drivers.png"
    fig.savefig(chart, dpi=160)

    # Score every order with the train-period model; keep which split each row was in.
    df["late_risk"] = model.predict_proba(df[FEATURES])[:, 1]
    df["split"] = np.where(df.purchased_at < TRAIN_END, "train",
                           np.where(df.purchased_at < TEST_END, "test", "unscored_period"))
    out = df[["order_id", "late_risk", "split"]]  # noqa: F841 (read by DuckDB below)
    con.execute("create schema if not exists ml")
    con.execute("""create or replace table ml.order_late_risk as
                   select order_id, late_risk, ntile(10) over (order by late_risk) as risk_decile, split from out""")
    con.close()

    mlflow.set_tracking_uri(f"sqlite:///{(ROOT / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("marketplace-pulse")
    with mlflow.start_run(run_name="late_delivery_lgbm"):
        mlflow.log_params({**PARAMS, "train_end": TRAIN_END, "test_end": TEST_END, "n_features": len(FEATURES)})
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(chart))
    return metrics


if __name__ == "__main__":
    main()
