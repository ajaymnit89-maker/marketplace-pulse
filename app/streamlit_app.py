"""Marketplace Pulse: late deliveries, unhappy customers, and what to do about them.

    uv run streamlit run app/streamlit_app.py

Reads app/app.duckdb (built by app/build_app_db.py), so it runs anywhere without the full warehouse.
"""

import sys
from pathlib import Path

import altair as alt
import anthropic
import duckdb
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai import analyst_agent

DB = ROOT / "app" / "app.duckdb"
BLUE, ORANGE, INK_2 = "#2a78d6", "#eb6834", "#52514e"

st.set_page_config(page_title="Marketplace Pulse", layout="wide")


@st.cache_resource
def con():
    return duckdb.connect(str(DB), read_only=True)


@st.cache_data
def q(sql):
    return con().sql(sql).df()


def bar(df, x, y, color=BLUE, sorted_=True, fmt=".1f", horizontal=False, title=None):
    """Bar chart of category x against value y; sorted by value unless sorted_=False (e.g. ordered deciles)."""
    if horizontal:  # at least 26px per row so no label is dropped
        enc = {"y": alt.Y(x, sort="-x" if sorted_ else None, title=None, axis=alt.Axis(labelLimit=220, labelOverlap=False)),
               "x": alt.X(y, title=title)}
        height = max(180, 26 * len(df) + 40)
    else:
        enc = {"x": alt.X(x, sort="-y" if sorted_ else None, title=None), "y": alt.Y(y, title=title)}
        height = 320
    return (alt.Chart(df).mark_bar(color=color, cornerRadiusEnd=4)
            .encode(**enc, tooltip=[x, alt.Tooltip(y, format=fmt)]).properties(height=height))


st.title("Marketplace Pulse")
st.caption("Olist Brazilian marketplace, 99k orders, Sep 2016 to Aug 2018. "
           "Pipeline: DuckDB, dbt, LightGBM, statsforecast, Claude. Data: Olist (CC BY-NC-SA 4.0).")

tabs = st.tabs(["Overview", "Delivery & reviews", "Late-risk model", "Forecast", "Segments", "Ask the data"])

# ---------------------------------------------------------------- Overview
with tabs[0]:
    k = q("""select sum(order_value) gmv, count(*) orders, sum(order_value) / count(*) aov,
                    100 * avg(is_late::int) filter (where is_delivered) late_pct, avg(review_score) review
             from marts.fct_orders where not is_canceled""").iloc[0]
    c = st.columns(5)
    c[0].metric("GMV", f"R${k.gmv / 1e6:.1f}M")
    c[1].metric("Orders", f"{k.orders:,.0f}")
    c[2].metric("Avg order value", f"R${k.aov:.0f}")
    c[3].metric("Late deliveries", f"{k.late_pct:.1f}%")
    c[4].metric("Avg review", f"{k.review:.2f} / 5")

    m = q("""select date_trunc('month', purchase_date) as month_start, sum(order_value) / 1e6 gmv_m,
                    100 * avg(is_late::int) filter (where is_delivered) late_pct
             from marts.fct_orders where not is_canceled and purchase_date between '2017-01-01' and '2018-08-31'
             group by 1 order by 1""")
    left, right = st.columns(2)
    left.subheader("GMV by month (R$ millions)")
    left.altair_chart(alt.Chart(m).mark_line(color=BLUE, strokeWidth=2, point=True).encode(
        x=alt.X("month_start:T", title=None), y=alt.Y("gmv_m:Q", title=None),
        tooltip=[alt.Tooltip("month_start:T", format="%b %Y"), alt.Tooltip("gmv_m:Q", format=".2f")]), use_container_width=True)
    right.subheader("Late-delivery rate by month (%)")
    right.altair_chart(alt.Chart(m).mark_line(color=ORANGE, strokeWidth=2, point=True).encode(
        x=alt.X("month_start:T", title=None), y=alt.Y("late_pct:Q", title=None),
        tooltip=[alt.Tooltip("month_start:T", format="%b %Y"), alt.Tooltip("late_pct:Q", format=".1f")]),
        use_container_width=True)
    st.info("Lateness spikes in peak months (12% in Nov 2017, 19% in Mar 2018) while the promise date stays fixed. "
            "Late orders are 1 in 15, but they drive most of the damage on the next tab.")

# ---------------------------------------------------------------- Delivery & reviews
with tabs[1]:
    left, right = st.columns(2)
    b = q("""select case when delay_days <= -7 then '7+ days early' when delay_days <= 0 then '0-6 days early'
                         when delay_days <= 3 then '1-3 days late' when delay_days <= 7 then '4-7 days late'
                         else '8+ days late' end bucket, min(delay_days) k,
                    100 * avg((review_score <= 2)::int) bad_pct, count(*) orders
             from marts.fct_orders where is_delivered and review_score is not null group by 1 order by k""")
    b["timing"] = b.k.map(lambda d: "late" if d > 0 else "on time")
    left.subheader("Share of 1-2 star reviews by delivery timing")
    left.altair_chart(alt.Chart(b).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("bucket:N", sort=list(b.bucket), title=None), y=alt.Y("bad_pct:Q", title="% 1-2 stars"),
        color=alt.Color("timing:N", scale=alt.Scale(domain=["on time", "late"], range=[BLUE, ORANGE]), title=None),
        tooltip=["bucket", alt.Tooltip("bad_pct:Q", format=".1f"), alt.Tooltip("orders:Q", format=",")]
    ).properties(height=320), use_container_width=True)

    s = q("""select customer_state state, 100 * avg(is_late::int) late_pct, count(*) orders
             from marts.fct_orders where is_delivered group by 1 having count(*) >= 300""")
    right.subheader("Late-delivery rate by customer state")
    right.altair_chart(bar(s, "state:N", "late_pct:Q", color=ORANGE, horizontal=True, title="% late"),
                       use_container_width=True)

    st.subheader("Why are 1-2 star customers unhappy? (Claude-classified reviews)")
    t = q("""select a.topic, f.is_late, count(*) n from ai.review_insights a join marts.fct_orders f using (order_id)
             group by 1, 2""")
    t["delivery"] = t.is_late.map({True: "late", False: "on time"}).fillna("not delivered")
    st.altair_chart(alt.Chart(t).mark_bar().encode(
        y=alt.Y("topic:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)), x=alt.X("n:Q", title="reviews"),
        color=alt.Color("delivery:N", scale=alt.Scale(domain=["on time", "late", "not delivered"],
                                                      range=[BLUE, ORANGE, "#9a9893"]), title="Order was"),
        tooltip=["topic", "delivery", alt.Tooltip("n:Q", format=",")]).properties(height=300),
        use_container_width=True)
    st.caption("10,839 Portuguese reviews translated and labelled by Claude Opus 5.5 (Batch API, structured output). "
               "Spot-check: translations 50/50 faithful, topics 49/50 correct.")
    topic = st.selectbox("Read what customers said", sorted(t.topic.unique()), index=None,
                         placeholder="Pick a complaint topic")
    if topic:
        quotes = q(f"""select translation_en from ai.review_insights where topic = '{topic}'
                       and length(translation_en) between 60 and 280 order by hash(order_id) limit 6""")
        for text in quotes.translation_en:
            st.markdown(f"> {text}")

# ---------------------------------------------------------------- Late-risk model
with tabs[2]:
    mm = q("select * from ml.late_model_metrics").iloc[0]
    c = st.columns(3)
    c[0].metric("PR-AUC (test)", f"{mm.pr_auc_model:.3f}", f"vs {mm.pr_auc_baseline:.3f} state baseline")
    c[1].metric("Late orders caught in top 10% risk", f"{100 * mm.capture_top10_model:.1f}%",
                f"vs {100 * mm.capture_top10_baseline:.1f}% baseline")
    c[2].metric("ROC-AUC (test)", f"{mm.roc_auc_model:.2f}", f"vs {mm.roc_auc_baseline:.2f} baseline")
    d = q("""select r.risk_decile decile, 100 * avg(f.is_late::int) late_pct, count(*) orders
             from ml.order_late_risk r join marts.fct_orders f using (order_id)
             where r.split = 'test' and f.is_delivered group by 1 order by 1""")
    left, right = st.columns(2)
    left.subheader("Actual late rate by predicted risk decile (Apr-Jul 2018)")
    left.altair_chart(bar(d, "decile:O", "late_pct:Q", color=ORANGE, sorted_=False, title="% late"),
                      use_container_width=True)
    right.subheader("What drives the risk score")
    right.image(str(ROOT / "docs" / "img" / "late_model_drivers.png"))
    st.caption("LightGBM trained on orders before Apr 2018, tested on Apr-Jul 2018. Features use only what is known "
               "at purchase time; seller history counts only orders whose outcome was already known.")

# ---------------------------------------------------------------- Forecast
with tabs[3]:
    f = q("select * from ml.category_forecast where week_start >= '2017-09-01' order by week_start")
    cat = st.selectbox("Series", sorted(f.category.unique()), index=0)
    s = f[f.category == cat]
    base = alt.Chart(s).encode(x=alt.X("week_start:T", title=None))
    st.altair_chart(alt.layer(
        base.mark_area(color=ORANGE, opacity=0.18).encode(y="lo_80:Q", y2="hi_80:Q"),
        base.mark_line(color=BLUE, strokeWidth=2).encode(y=alt.Y("actual_orders:Q", title="orders per week"),
                                                         tooltip=["week_start:T", "actual_orders:Q"]),
        base.mark_line(color=ORANGE, strokeWidth=2).encode(y="forecast:Q", tooltip=["week_start:T", "forecast:Q"]),
    ).properties(height=340), use_container_width=True)
    bt = q("select category, round(100 * mape, 1) as mape_pct from ml.forecast_backtest order by mape")
    st.caption(f"Blue: actual. Orange: 8-week forecast with 80% interval ({s.model.iloc[0]}). Backtest: 4 rolling "
               "4-week windows. The naive model beat ETS and ARIMA; the test window held shocks (late-May 2018 "
               "truckers' strike) that no model saw coming.")
    st.dataframe(bt, hide_index=True)

# ---------------------------------------------------------------- Segments
with tabs[4]:
    seg = q("""select segment, count(*) customers, median(recency_days) recency_days, avg(frequency) orders,
                      median(monetary) median_spend, avg(avg_review) avg_review, avg(late_share) late_share
               from ml.customer_segments group by 1 order by 2 desc""")
    st.altair_chart(bar(seg, "segment:N", "customers:Q", horizontal=True, fmt=",", title="customers"),
                    use_container_width=True)
    st.dataframe(seg.round(2), hide_index=True)
    st.info("'Unhappy, delivered on time' (12.8k customers) is not a delivery problem: their reviews are mostly about "
            "missing items, items not as described, damage and wrong items.")

# ---------------------------------------------------------------- Ask the data
with tabs[5]:
    st.subheader("Ask a question about the business")
    st.caption("Claude writes SQL against the governed marts, using the dbt metric definitions, on a read-only "
               "sandboxed connection. It scored 20/20 on a test set with SQL-verified answers.")
    examples = pd.read_csv(ROOT / "docs" / "agent_eval_results.csv")
    with st.expander("20 verified example questions (no key needed)"):
        pick = st.selectbox("Question", examples.question, index=None, placeholder="Pick one")
        if pick:
            row = examples[examples.question == pick].iloc[0]
            st.markdown(row.answer)
            st.code(row.sql, language="sql")

    key = st.text_input("Your Anthropic API key (used for this session only, never stored)", type="password")
    question = st.text_input("Your question", placeholder="Which sellers have the most 'missing items' complaints?")
    if st.button("Ask", disabled=not (key and question)):
        with st.spinner("Querying..."):
            try:
                ans = analyst_agent.ask(question, client=anthropic.Anthropic(api_key=key))
            except anthropic.AuthenticationError:
                st.error("That API key was rejected.")
            except anthropic.APIError as e:
                st.error(f"API error: {e.__class__.__name__}")
            else:
                st.markdown(ans.text)
                if ans.last_table is not None:
                    st.dataframe(ans.last_table, hide_index=True)
                for sql, _ in ans.queries:
                    st.code(sql, language="sql")
                st.caption(f"Cost of this answer: ${ans.cost_usd:.3f}")
