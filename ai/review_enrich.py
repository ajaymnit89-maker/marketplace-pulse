"""Translate and classify 1-2 star Portuguese reviews with Claude, via the Message Batches API.

Each request carries 50 reviews and must return JSON matching SCHEMA. Results go to ai.review_insights.
Reviews already in that table are skipped. The submitted batch id is saved to data/ai/, so rerunning after an
interruption picks the same batch back up instead of paying for it twice.

    python ai/review_enrich.py --limit 100   # pilot
    python ai/review_enrich.py               # everything not yet classified
"""

import argparse
import json
import time
from pathlib import Path

import anthropic
import duckdb
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
PENDING = ROOT / "data" / "ai" / "pending_batch.txt"
MODEL = "claude-opus-5-5"
CHUNK = 50
PRICE_IN, PRICE_OUT = 4 / 1e6 * 0.5, 20 / 1e6 * 0.5  # Opus 5.5, batch discount

TOPICS = [
    "late_delivery", "not_received", "wrong_item", "missing_items", "damaged_or_defective",
    "not_as_described", "seller_service", "refund_or_cancellation", "other",
]
SCHEMA = {
    "type": "object",
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "translation_en": {"type": "string"},
                    "topic": {"type": "string", "enum": TOPICS},
                    "sentiment": {"type": "string", "enum": ["negative", "mixed", "positive"]},
                    "mentions_delay": {"type": "boolean"},
                },
                "required": ["id", "translation_en", "topic", "sentiment", "mentions_delay"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reviews"],
    "additionalProperties": False,
}
SYSTEM = f"""You classify customer reviews from Olist, a Brazilian online marketplace. Reviews are in Portuguese.

For every review in the input, return one entry with the same id:
- translation_en: a faithful, plain English translation of the title and comment together.
- topic: the customer's main complaint, one of: {", ".join(TOPICS)}.
  late_delivery = arrived, and the main complaint is that delivery was slow or later than promised
  (even if it arrived within the stated deadline). not_received = never arrived or still waiting.
  missing_items = part of a multi-item order did not arrive. not_as_described = arrived, but differs from the
  listing (size, color, model, quality). seller_service = seller was unresponsive or unhelpful.
  Use other only when none of these fit, including reviews with no real complaint.
- sentiment: the tone of the text itself, which can differ from the star rating.
- mentions_delay: true if the text mentions waiting, slowness or a missed date at all, even if it is not the main topic.

Return every id exactly once. Do not skip reviews."""


def chunks(rows, size=CHUNK):
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def build_request(i, rows):
    payload = [{"id": r["order_id"], "title": r["title"], "comment": r["comment"]} for r in rows]
    return Request(
        custom_id=f"chunk-{i}",
        params=MessageCreateParamsNonStreaming(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        ),
    )


def parse_result(text, valid_ids):
    """Entries whose id is a review we could have sent; duplicates collapse to one."""
    return list({r["id"]: r for r in json.loads(text)["reviews"] if r["id"] in valid_ids}.values())


def main(limit=None):
    load_dotenv(ROOT / ".env")
    client = anthropic.Anthropic()
    con = duckdb.connect(str(DB))
    con.execute("create schema if not exists ai")
    con.execute("""create table if not exists ai.review_insights (
        order_id varchar primary key, translation_en varchar, topic varchar, sentiment varchar,
        mentions_delay boolean, model varchar, classified_at timestamp default current_timestamp)""")

    if PENDING.exists():
        batch_id = PENDING.read_text().strip()
        print(f"Resuming batch {batch_id}")
        con.close()
    else:
        rows = con.sql(f"""
            select r.order_id, r.review_comment_title as title, r.review_comment_message as comment
            from staging.stg_order_reviews r
            where r.review_score <= 2 and r.review_comment_message is not null
              and r.order_id not in (select order_id from ai.review_insights)
            order by r.order_id
            {f"limit {int(limit)}" if limit else ""}
        """).df().to_dict("records")
        if not rows:
            print("Nothing left to classify.")
            con.close()
            return
        requests = [build_request(i, c) for i, c in enumerate(chunks(rows))]
        batch_id = client.messages.batches.create(requests=requests).id
        PENDING.parent.mkdir(parents=True, exist_ok=True)
        PENDING.write_text(batch_id)
        print(f"Submitted batch {batch_id}: {len(rows)} reviews in {len(requests)} requests")
    con.close()  # don't hold the warehouse file open while the batch runs (dbt needs it)

    while (batch := client.messages.batches.retrieve(batch_id)).processing_status != "ended":
        c = batch.request_counts
        print(f"  {batch.processing_status}: {c.succeeded} done, {c.processing} processing")
        time.sleep(30)

    con = duckdb.connect(str(DB))
    candidates = {x for (x,) in con.execute(
        "select order_id from staging.stg_order_reviews where review_score <= 2 and review_comment_message is not null"
    ).fetchall()}
    tokens_in = tokens_out = saved = 0
    problems = []
    for result in client.messages.batches.results(batch_id):
        if result.result.type != "succeeded":
            problems.append(f"{result.custom_id}: {result.result.type}")
            continue
        msg = result.result.message
        tokens_in += msg.usage.input_tokens
        tokens_out += msg.usage.output_tokens
        if msg.stop_reason != "end_turn":  # refusal or max_tokens: no usable JSON
            problems.append(f"{result.custom_id}: stop_reason {msg.stop_reason}")
            continue
        entries = parse_result(next(b.text for b in msg.content if b.type == "text"), candidates)
        for e in entries:
            con.execute("insert or ignore into ai.review_insights (order_id, translation_en, topic, sentiment, "
                        "mentions_delay, model) values (?, ?, ?, ?, ?, ?)",
                        [e["id"], e["translation_en"], e["topic"], e["sentiment"], e["mentions_delay"], MODEL])
        saved += len(entries)

    PENDING.unlink()
    left = len(candidates) - con.execute("select count(*) from ai.review_insights").fetchall()[0][0]
    con.close()
    print(f"Saved {saved} reviews. Tokens in {tokens_in:,}, out {tokens_out:,}, "
          f"cost ~${tokens_in * PRICE_IN + tokens_out * PRICE_OUT:.2f}. {left:,} low-star reviews still unclassified.")
    for p in problems:
        print("WARN", p)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="classify at most this many reviews (pilot)")
    main(ap.parse_args().limit)
