from types import SimpleNamespace

import pandas as pd

from ml.forecast import mape
from ml.late_delivery import FEATURES, capture_at
from ml.segments import name_segment

# Columns only known after the order ships or arrives. None may be a model feature.
POST_PURCHASE = {
    "is_late", "delay_days", "delivery_days", "delivered_at", "shipped_at", "approved_at",
    "review_score", "has_review_comment", "is_delivered", "order_status", "seller_shipped_late",
}


def test_no_post_purchase_features():
    assert not POST_PURCHASE & set(FEATURES)


def test_capture_at():
    y = [1, 0, 0, 0, 0, 0, 0, 0, 0, 1]
    score = [0.9, 0.8, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.2]
    assert capture_at(y, score, 0.1) == 0.5  # top 1 of 10 rows holds one of the two positives
    assert capture_at(y, score, 0.3) == 1.0


def test_mape():
    assert mape(pd.Series([100.0, 200.0]), pd.Series([110.0, 180.0])) == 0.1


def test_segment_names():
    def p(late=0.0, freq=1.0, review=4.5, recency=100):
        return SimpleNamespace(late_share=late, frequency=freq, avg_review=review, recency_days=recency)

    assert name_segment(p(late=1.0, review=2.0), 200) == "Burned by late delivery"
    assert name_segment(p(freq=2.1), 200) == "Repeat buyers"
    assert name_segment(p(review=1.8), 200) == "Unhappy, delivered on time"
    assert name_segment(p(recency=380), 200) == "Happy, lapsed"
    assert name_segment(p(recency=120), 200) == "Happy, recent"


def test_review_parse_keeps_only_valid_unique_ids():
    import json

    from ai.review_enrich import chunks, parse_result

    entry = {"translation_en": "x", "topic": "other", "sentiment": "negative", "mentions_delay": False}
    text = json.dumps({"reviews": [{"id": "a", **entry}, {"id": "a", **entry}, {"id": "zzz", **entry}]})
    assert [e["id"] for e in parse_result(text, {"a", "b"})] == ["a"]
    assert [len(c) for c in chunks(list(range(120)))] == [50, 50, 20]


def test_sql_guard():
    from ai.analyst_agent import check_sql

    assert check_sql("select count(*) from marts.fct_orders") is None
    assert check_sql("with x as (select 1) select * from x;") is None
    assert check_sql("drop table marts.fct_orders") is not None
    assert check_sql("select 1; select 2") is not None
    assert check_sql("select * from raw.orders") is not None
    assert check_sql("select * from staging.stg_orders") is not None


def test_eval_grader():
    from ai.eval_agent import numbers_in, passes

    assert numbers_in("GMV was R$15.7M and 1,234 orders") == [15.7e6, 1234.0]
    assert passes("About R$15.74 million in total.", 15_735_527, ("rel", 0.01))
    assert not passes("About R$14 million.", 15_735_527, ("rel", 0.01))
    assert passes("The on-time rate is 93.2%.", 93.22, ("abs", 0.15))
    assert passes("Alagoas (AL) is the worst.", "AL", None)
