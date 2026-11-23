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
