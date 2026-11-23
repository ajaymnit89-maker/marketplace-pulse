"""Weekly order forecast for the top 10 categories and the total.

Backtests AutoETS and AutoARIMA against naive baselines (4 rolling 4-week windows), then forecasts 8 weeks ahead
with the model that had the lowest backtest error overall. Writes ml.category_forecast and ml.forecast_backtest.
"""

from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import mlflow
import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA, AutoETS, Naive, WindowAverage

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
FIRST_WEEK, LAST_WEEK = "2017-01-02", "2018-08-13"  # orders thin out after mid-Aug 2018
HORIZON = 8
MODELS = {
    "AutoETS": AutoETS(season_length=1),
    "AutoARIMA": AutoARIMA(season_length=1),
    "Naive": Naive(),
    "WindowAverage": WindowAverage(window_size=4),
}


def mape(actual, forecast):
    return (abs(actual - forecast) / actual).mean()


def main():
    con = duckdb.connect(str(DB))
    weekly = con.sql(f"""
        with top as (
            select p.category from marts.fct_order_items i join marts.dim_product p using (product_id)
            where not i.is_canceled group by 1 order by count(distinct i.order_id) desc limit 10
        ), weeks as (
            select date_trunc('week', i.purchase_date) as ds, p.category, count(distinct i.order_id) as y
            from marts.fct_order_items i join marts.dim_product p using (product_id)
            where not i.is_canceled and p.category in (select category from top)
            group by 1, 2
            union all
            select date_trunc('week', purchase_date), 'ALL ORDERS', count(*)
            from marts.fct_orders where not is_canceled group by 1
        )
        select category as unique_id, ds::timestamp as ds, y::double as y from weeks
        where ds between '{FIRST_WEEK}' and '{LAST_WEEK}'
        order by 1, 2
    """).df()

    sf = StatsForecast(models=list(MODELS.values()), freq="W-MON")
    cv = sf.cross_validation(df=weekly, h=4, n_windows=4, step_size=4)
    scores = pd.Series({m: mape(cv.y, cv[m]) for m in MODELS}).sort_values()
    print("Backtest MAPE (4 windows x 4 weeks, all series):")
    print(scores.round(3).to_string())
    best = scores.index[0]

    # refit only the winner: the naive baselines do not all produce intervals
    fc = StatsForecast(models=[MODELS[best]], freq="W-MON").forecast(df=weekly, h=HORIZON, level=[80])
    fc = fc[["unique_id", "ds", best, f"{best}-lo-80", f"{best}-hi-80"]]
    fc.columns = ["unique_id", "ds", "forecast", "lo_80", "hi_80"]
    out = weekly.merge(fc, on=["unique_id", "ds"], how="outer").assign(model=best)
    per_series = cv.groupby("unique_id").apply(lambda g: mape(g.y, g[best]), include_groups=False)
    backtest = per_series.rename("mape").reset_index().assign(model=best)  # noqa: F841

    con.execute("create schema if not exists ml")
    con.execute("create or replace table ml.category_forecast as select unique_id as category, ds::date as week_start, "
                "y as actual_orders, forecast, lo_80, hi_80, model from out order by 1, 2")
    con.execute("create or replace table ml.forecast_backtest as select unique_id as category, mape, model from backtest")
    con.close()

    total = out[out.unique_id == "ALL ORDERS"]
    fig, ax = plt.subplots(figsize=(9, 3.4), facecolor="#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ax.plot(total.ds, total.y, color="#2a78d6", lw=2, label="actual")
    ax.plot(total.ds, total.forecast, color="#eb6834", lw=2, label=f"forecast ({best})")
    ax.fill_between(total.ds, total.lo_80, total.hi_80, color="#eb6834", alpha=0.18, lw=0, label="80% interval")
    ax.set_title("Weekly orders: actual and 8-week forecast", loc="left", fontweight="bold")
    ax.set_ylim(0, None)
    ax.legend(frameon=False, loc="upper left")
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color="#e4e3df")
    fig.tight_layout()
    chart = ROOT / "docs" / "img" / "forecast_total_orders.png"
    fig.savefig(chart, dpi=160)

    mlflow.set_tracking_uri(f"sqlite:///{(ROOT / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("marketplace-pulse")
    with mlflow.start_run(run_name="weekly_forecast"):
        mlflow.log_params({"best_model": best, "horizon_weeks": HORIZON, "series": weekly.unique_id.nunique()})
        mlflow.log_metrics({f"mape_{m}": v for m, v in scores.items()})
        mlflow.log_artifact(str(chart))
    return scores


if __name__ == "__main__":
    main()
