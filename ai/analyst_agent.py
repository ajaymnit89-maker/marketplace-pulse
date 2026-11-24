"""'Ask the data': Claude answers business questions by writing SQL against the governed marts.

Safety comes from the connection, not from parsing SQL: the warehouse is opened read-only with external access
(files, network, extensions) disabled and locked, so a query can only read tables already in the file. Queries
are limited to the marts / ml / ai schemas by a schema check, capped at MAX_ROWS rows and TIMEOUT_S seconds.

    python ai/analyst_agent.py "Which 5 states have the highest late-delivery rate?"
"""

import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
import duckdb
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# Full warehouse locally; the slim committed copy (app/build_app_db.py) when deployed.
DB = next((p for p in (ROOT / "data" / "warehouse.duckdb", ROOT / "app" / "app.duckdb") if p.exists()), ROOT / "data" / "warehouse.duckdb")
METRICS = ROOT / "dbt" / "models" / "marts" / "metrics.md"
MODEL = "claude-opus-5-5"
ALLOWED_SCHEMAS = ("marts", "ml", "ai")
MAX_ROWS, TIMEOUT_S, MAX_TURNS = 200, 15, 8

TOOL = {
    "name": "run_sql",
    "description": "Run one read-only DuckDB SQL query against the warehouse and get up to 200 rows back as CSV. "
                   "Qualify every table with its schema (marts., ml., ai.).",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"sql": {"type": "string", "description": "A single SELECT or WITH query."}},
        "required": ["sql"],
        "additionalProperties": False,
    },
}


@dataclass
class Answer:
    text: str
    queries: list = field(default_factory=list)  # (sql, DataFrame or error string)
    cost_usd: float = 0.0

    @property
    def last_table(self):
        return next((r for _, r in reversed(self.queries) if isinstance(r, pd.DataFrame)), None)


def connect():
    return duckdb.connect(str(DB), read_only=True,
                          config={"enable_external_access": False, "lock_configuration": True})


def check_sql(sql):
    """Return an error message, or None if the query may run."""
    s = sql.strip().rstrip(";")
    if ";" in s:
        return "Send one statement at a time."
    if not re.match(r"(?is)^\s*(select|with)\b", s):
        return "Only SELECT / WITH queries are allowed."
    schemas = {m.lower() for m in re.findall(r"\b([a-z_]+)\s*\.\s*[a-z_]+", s, re.IGNORECASE)}
    blocked = schemas & {"raw", "staging", "intermediate", "information_schema", "main", "pg_catalog"}
    if blocked:
        return f"Use the governed schemas only ({', '.join(ALLOWED_SCHEMAS)}), not {', '.join(sorted(blocked))}."
    return None


def run_sql(con, sql):
    if err := check_sql(sql):
        return err
    timer = threading.Timer(TIMEOUT_S, con.interrupt)
    timer.start()
    try:
        return con.sql(sql).limit(MAX_ROWS).df()
    except duckdb.Error as e:  # SQL errors and timeouts go back to Claude so it can fix the query
        return f"Error: {e}"
    finally:
        timer.cancel()


def schema_doc(con):
    rows = con.execute(f"""
        select table_schema || '.' || table_name, string_agg(column_name || ' ' || data_type, ', ' order by ordinal_position)
        from information_schema.columns where table_schema in {ALLOWED_SCHEMAS}
        group by 1 order by 1
    """).fetchall()
    return "\n".join(f"- {t}({cols})" for t, cols in rows)


def system_prompt(con):
    metrics = re.sub(r"{%.*?%}", "", METRICS.read_text(encoding="utf-8")).strip()
    return f"""You are a business intelligence analyst for Olist, a Brazilian online marketplace (orders Sep 2016 to
Aug 2018, values in BRL). Answer the user's question with data from the warehouse, using the run_sql tool.

Rules:
- Use the metric definitions below exactly. If a question uses a metric name defined here, compute it this way.
- Query only these tables. Check numbers with a query rather than guessing.
- Exclude canceled orders (is_canceled) unless the question is about cancellations.
- Answer in 1-4 sentences with the key numbers, then state any assumption you made. Do not invent data you did not
  query. If the data cannot answer the question, say so.

Tables:
{schema_doc(con)}

Notes: fct_orders is one row per order; fct_order_items one row per item; dim_customer one row per person
(customer_unique_id). ml.order_late_risk holds model scores; ml.customer_segments the KMeans segments;
ai.review_insights Claude's topic labels for 1-2 star reviews (joined on order_id).

{metrics}"""


def ask(question, client=None):
    load_dotenv(ROOT / ".env")
    client = client or anthropic.Anthropic()
    con = connect()
    system = [{"type": "text", "text": system_prompt(con), "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": question}]
    answer = Answer(text="")
    try:
        for _ in range(MAX_TURNS):
            response = client.beta.messages.create(
                model=MODEL, max_tokens=16000, system=system, tools=[TOOL], messages=messages,
                output_config={"effort": "high"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            u = response.usage  # Opus 5.5: $4 in, $20 out, $5 cache write, $0.20 cache read per M tokens
            answer.cost_usd += (u.input_tokens * 4 + u.output_tokens * 20 + (u.cache_creation_input_tokens or 0) * 5
                                + (u.cache_read_input_tokens or 0) * 0.2) / 1e6
            if response.stop_reason == "refusal":
                answer.text = "The model declined to answer this question."
                return answer
            messages.append({"role": "assistant", "content": response.content})
            calls = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not calls:
                answer.text = "\n".join(b.text for b in response.content if b.type == "text").strip()
                return answer
            results = []
            for call in calls:
                out = run_sql(con, call.input["sql"])
                answer.queries.append((call.input["sql"], out))
                is_table = isinstance(out, pd.DataFrame)
                results.append({"type": "tool_result", "tool_use_id": call.id,
                                "content": out.to_csv(index=False) if is_table else out, "is_error": not is_table})
            messages.append({"role": "user", "content": results})
        answer.text = f"Stopped after {MAX_TURNS} tool calls without a final answer."
        return answer
    finally:
        con.close()


if __name__ == "__main__":
    a = ask(" ".join(sys.argv[1:]) or "What share of delivered orders arrived late?")
    for sql, _ in a.queries:
        print(f"--- SQL\n{sql}")
    print(f"--- Answer\n{a.text}")
