# Power BI report spec

The semantic model is done and checked: 10 tables, 8 relationships, 26 measures, and the totals match the dbt marts to the cent. This file is the plan for the report pages, which you design in Power BI Desktop.

## Before you start

1. Run `uv run python app/build_app_db.py` to write the Parquet files to `data/export/`. On a fresh clone it builds them from the committed `app/app.duckdb`, so you don't need the raw data.
2. Open `powerbi/MarketplacePulse.pbip`. If your copy of the repo lives somewhere else, open Transform data > Edit parameters, point `DataFolder` at your `data/export/` folder, then Refresh.
3. Save as you go. The project is plain text (TMDL plus report JSON), so every change shows up in git diffs.

Use measures, not raw columns, so every number agrees with the dbt metric definitions. For product and seller visuals, use the measures in the "By product & seller" folder of the Order Items table, because the order-level measures don't filter through those tables.

## Page 1: Executive overview

The question: how big is the business, and is delivery getting worse?

| Visual | Fields |
|---|---|
| 6 KPI cards | `GMV`, `Order Count`, `AOV`, `Late Rate`, `Avg Review Score`, `GMV YoY %` |
| Line: GMV by month | X `Date[year_month]`, Y `GMV` |
| Line: Late Rate by month | X `Date[year_month]`, Y `Late Rate` |
| Slicers | `Date[date_day]` (between), `Customer[state]` |

Callout to add: late deliveries peak in Nov 2017 (12%) and Mar 2018 (19%).

## Page 2: Delivery and reviews

The question: what does a late delivery cost?

| Visual | Fields |
|---|---|
| Column: bad reviews by timing | X `Orders[Delay Bucket]` (already sorted), Y `Bad Review Share`. Expect about 9%, 11%, 32%, 68% and 79%, left to right |
| Bar or filled map: late rate by state | `Customer[state]`, `Late Rate`, sorted descending |
| Bar: late rate by category | `Product[category]`, `Late Rate (items)` (top 15 by `Orders (items)`) |
| KPI cards | `Late Orders`, `Late GMV`, `Avg Delay Days (Late)`, `Seller Late-ship Rate` |

Callout to add: only about 28% of late orders shipped late from the seller. The rest left on time and were late anyway.

## Page 3: Why customers are unhappy (AI)

The question: what do 1-2 star customers actually complain about?

| Visual | Fields |
|---|---|
| Stacked bar: complaint topics | Y `Review Insight[topic]`, X `Classified Reviews`, legend `Orders[is_late]` |
| Donut | `Review Insight[sentiment]`, `Classified Reviews` |
| Table: what customers said | `Review Insight[topic]`, `Review Insight[translation_en]`, `Orders[customer_state]` |
| Slicer | `Review Insight[topic]` |

Subtitle to add: "10,839 Portuguese reviews translated and labelled by Claude".

## Page 4: Risk model and customer segments

The question: can we see trouble coming, and who are we losing?

| Visual | Fields |
|---|---|
| Column: late rate by risk decile | X `Late Risk[risk_decile]`, Y `Late Rate`, page filter `Late Risk[split]` = test |
| Bar: orders by segment | `Customer Segment[segment]`, `Order Count` |
| Matrix: segment profile | rows `Customer Segment[segment]`; values `Customers`, `Avg Review Score`, `Late Rate`, `AOV` |

Callout to add: the top risk decile runs about 3x the average late rate.

## Page 5: Demand forecast

| Visual | Fields |
|---|---|
| Line: actual vs forecast | X `Forecast[week_start]`, Y `Actual Orders (Forecast)` and `Forecast Orders`; error bars or a band from `Forecast[lo_80]` / `Forecast[hi_80]` |
| Slicer | `Forecast[category]`, single select, default `ALL ORDERS` |

Note to add: the naive model beat ETS and ARIMA in backtesting, because the test window held real shocks.

## Style

- Blue `#2a78d6` for on time / baseline, orange `#eb6834` for late / risk. These are the same colors as the Streamlit app and the notebook charts.
- One accent color per visual, and labels only where they help.
- Export each page as PNG to `docs/img/powerbi_*.png` for the README.
