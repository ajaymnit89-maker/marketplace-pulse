"""Score the analyst agent on 20 questions with known answers.

Each reference answer comes from a hand-written SQL query run at eval time, so it stays correct if the data
is rebuilt. A question passes if the agent's answer text contains the reference value (numbers within the stated
tolerance, labels as a case-insensitive substring). Results go to docs/agent_eval_results.csv.

Costs real money: about $0.20 per full run on Opus 5.5 (system prompt is cached).
"""

import re
import sys
from pathlib import Path

import pandas as pd

from ai.analyst_agent import ask, connect

ROOT = Path(__file__).resolve().parents[1]

# (question, reference sql returning one value, tolerance: ("rel", x) | ("abs", x) | None for a label)
CASES = [
    ("What is total GMV in BRL, excluding canceled orders?",
     "select sum(order_value) from marts.fct_orders where not is_canceled", ("rel", 0.01)),
    ("How many orders were placed, excluding canceled ones?",
     "select count(*) from marts.fct_orders where not is_canceled", ("rel", 0.001)),
    ("What is the average order value (AOV) in BRL?",
     "select sum(order_value) / count(*) from marts.fct_orders where not is_canceled", ("rel", 0.01)),
    ("What is the on-time delivery rate, as a percentage?",
     "select 100 * avg((not is_late)::int) from marts.fct_orders where is_delivered and not is_canceled", ("abs", 0.15)),
    ("What percentage of delivered orders to Rio de Janeiro (RJ) customers arrived late?",
     "select 100 * avg(is_late::int) from marts.fct_orders where is_delivered and not is_canceled and customer_state = 'RJ'",
     ("abs", 0.15)),
    (("Among customer states with at least 300 delivered orders, which state has the highest late-delivery rate? "
     "Give the two-letter state code."),
     """select customer_state from marts.fct_orders where is_delivered and not is_canceled
        group by 1 having count(*) >= 300 order by avg(is_late::int) desc limit 1""", None),
    ("What is the average review score of orders that arrived late?",
     "select avg(review_score) from marts.fct_orders where is_late and not is_canceled", ("abs", 0.02)),
    ("What is the repeat customer rate, as a percentage?",
     "select 100 * avg(is_repeat_customer::int) from marts.dim_customer", ("abs", 0.1)),
    ("How many sellers are on the platform?", "select count(*) from marts.dim_seller", ("rel", 0.001)),
    ("Which product category has the most orders? Give the category name as stored in the data.",
     """select p.category from marts.fct_order_items i join marts.dim_product p using (product_id)
        where not i.is_canceled group by 1 order by count(distinct i.order_id) desc limit 1""", None),
    ("Which purchase month had the highest GMV? Answer in YYYY-MM format.",
     """select strftime(purchase_date, '%Y-%m') from marts.fct_orders where not is_canceled
        group by 1 order by sum(order_value) desc limit 1""", None),
    ("What percentage of orders were mainly paid by credit card?",
     "select 100 * avg((main_payment_type = 'credit_card')::int) from marts.fct_orders where not is_canceled",
     ("abs", 0.15)),
    ("On average, how many days did delivered orders take from purchase to delivery?",
     "select avg(delivery_days) from marts.fct_orders where is_delivered and not is_canceled", ("abs", 0.1)),
    ("How many customers are in the 'Burned by late delivery' segment?",
     "select count(*) from ml.customer_segments where segment = 'Burned by late delivery'", ("rel", 0.001)),
    ("For orders in the model's test period, what percentage of orders in the highest risk decile (10) arrived late?",
     """select 100 * avg(f.is_late::int) from ml.order_late_risk r join marts.fct_orders f using (order_id)
        where r.split = 'test' and r.risk_decile = 10 and f.is_delivered""", ("abs", 0.2)),
    ("What is the total GMV in BRL of orders that arrived late?",
     "select sum(order_value) from marts.fct_orders where is_late and not is_canceled", ("rel", 0.01)),
    ("How many orders received a 1-star review?",
     "select count(*) from marts.fct_orders where review_score = 1", ("rel", 0.001)),
    ("Freight is what percentage of GMV?",
     "select 100 * sum(freight_value) / sum(order_value) from marts.fct_orders where not is_canceled", ("abs", 0.1)),
    ("Among 1-2 star reviews classified by AI, what is the most common complaint topic? Give the topic label.",
     "select topic from ai.review_insights group by 1 order by count(*) desc limit 1", None),
    ("How many AI-classified 1-2 star reviews are about missing items?",
     "select count(*) from ai.review_insights where topic = 'missing_items'", ("rel", 0.001)),
]


def numbers_in(text):
    """All numbers in the text, reading '15.7M' / '15.7 million' / '1,234' correctly."""
    out = []
    for num, suffix in re.findall(r"(\d[\d,]*\.?\d*)\s*(million|thousand|[mMkK]\b)?", text):
        v = float(num.replace(",", ""))
        out.append(v * {"m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}.get(suffix.lower(), 1))
    return out


def passes(answer, expected, tol):
    if tol is None:
        return str(expected).lower() in answer.lower()
    kind, x = tol
    limit = abs(expected) * x if kind == "rel" else x
    return any(abs(v - expected) <= limit for v in numbers_in(answer))


def main(limit=None):
    con = connect()
    expected = [con.execute(sql).fetchall()[0][0] for _, sql, _ in CASES]
    con.close()
    rows = []
    for (question, _, tol), exp in list(zip(CASES, expected, strict=True))[:limit]:
        a = ask(question)
        ok = passes(a.text, exp, tol)
        rows.append({"question": question, "expected": exp, "passed": ok, "cost_usd": a.cost_usd, "answer": a.text,
                     "sql": "\n---\n".join(s for s, _ in a.queries)})
        print(f"{'PASS' if ok else 'FAIL'}  {question[:70]}  (expected {exp})")
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "docs" / "agent_eval_results.csv", index=False)
    print(f"\n{df.passed.sum()}/{len(df)} passed ({100 * df.passed.mean():.0f}%), cost ${df.cost_usd.sum():.2f}")
    return df


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
