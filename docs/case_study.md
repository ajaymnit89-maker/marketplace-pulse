# Case study: Marketplace Pulse

## The problem

Olist connects small Brazilian sellers to large marketplaces and handles delivery through carriers. Every order gets a promised delivery date. I wanted to know what it costs when that promise breaks, where the breaks come from, and whether the business can see them coming.

The data is Olist's public dataset: 99,441 orders from September 2016 to August 2018, across nine tables (orders, items, payments, reviews, customers, sellers, products, geolocation and a category translation). Reviews are in Portuguese.

## What I built

**Data engineering.** A Python loader puts the nine CSVs into DuckDB and checks row counts, key uniqueness, nulls and orphaned rows before anything else runs. dbt then builds staging views, a few intermediate models and a star schema with two facts (`fct_orders`, `fct_order_items`) and four dimensions. Forty-four dbt tests guard keys, relationships and accepted values. Two custom tests matter most: the marts must keep every order and every real of GMV from the raw files, and the late flag must agree with the delay in days. Metric definitions (GMV, AOV, on-time rate, repeat rate) live in one dbt doc that the dashboards and the AI agent both use.

**Analysis.** A notebook tests how delivery timing relates to reviews and repeat purchases. I ran the review comparison within each region to rule out region as the explanation, and limited the repeat-purchase test to first orders placed at least six months before the data ends, so every customer had time to come back.

**Machine learning.** A LightGBM classifier predicts whether an order will be late, using only what is known when the order is placed. The seller's track record counts only earlier orders whose promised date had already passed. A dbt test checks that, because it's the easiest place for future information to leak in. The model trains on orders before April 2018 and is tested on April to July 2018. A weekly demand forecast for the top 10 categories is backtested against naive baselines, and KMeans splits customers into five segments named from their profiles.

**AI.** Claude Opus 5.5 translated and labelled all 10,839 one- and two-star reviews with a complaint topic, a sentiment and a delay flag, through the Batch API with a fixed JSON schema. I ran a 100-review pilot first and checked 50 labels against the Portuguese by hand (49 right). That also showed that one topic definition was ambiguous, so I fixed it before the full run, which cost $12.75. A second Claude component answers business questions by writing SQL against the marts. It runs on a read-only connection with file and network access locked off, and scored 20/20 on a test set whose answers come from hand-written SQL.

**Delivery.** A Prefect flow runs everything with one command. GitHub Actions runs lint, unit tests and the pipeline on a committed 1,000-order sample. The results go to a Streamlit app and a Power BI semantic model stored as TMDL, whose measures match the dbt marts to the cent.

## What the data says

- A late delivery is the strongest driver of bad reviews in the data. Arriving one to three days late triples the share of one- and two-star reviews (about 10% to 32%). After four days late, most reviews are one or two stars.
- Customers whose first order was late came back about a quarter less often (3.05% against 4.13%).
- 72% of late orders left the seller on time, so the carrier leg and the promised date matter more than seller behaviour. Only 11 of 425 sellers with 50 or more orders are late more often than their volume predicts.
- Geography and peak months drive lateness. Product category barely does.
- Customers who were unhappy without a late delivery mostly complain about missing items, items not as described, damage and wrong items. That is a fulfillment problem, and it needs a different fix.

## Decisions and corrections

- **I dropped a feature that looked important.** Purchase month came out as the top SHAP driver, but removing it cost only 0.005 PR-AUC. It was memorising the one-off spike in early 2018, and keeping it would have made the driver chart misleading.
- **I reported a forecast that lost to the baseline.** ETS and ARIMA did worse than "next week equals this week", because the test window held the May 2018 truckers' strike. The app uses the naive forecast with intervals and says why.
- **I checked every claim against the output.** Drafting the notebook text before the results came back produced four wrong statements, including an overstated seller finding. Reconciling the Power BI measures against SQL caught a DAX bug: a blank review score compared as zero, which counted orders with no review as bad reviews.
- **I made the runs reproducible.** Reloading the data changed the row order and shifted model results slightly between runs. Reading inputs in a fixed order made repeated runs identical.

## Limits and next steps

The repeat-purchase effect is an association; a holdout test (for example, longer promised dates in high-risk routes) would show whether fixing lateness actually brings customers back. The risk model's PR-AUC of 0.110 is modest because most lateness happens in the carrier leg, which the data does not describe. Carrier, route and tracking data would be the first thing to add. The data ends in 2018, so the forecast is a method demonstration, not a current prediction.
