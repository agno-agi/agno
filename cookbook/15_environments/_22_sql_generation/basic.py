"""
SQL Generation - Basic
======================

Generate one recursive SQLite query that accepts or rejects inventory reservations
from evolving stock, then execute it against a private in-memory fixture. Functional
rows decide the score; formatting does not.
"""

import sqlite3

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer, Score
from pydantic import BaseModel, Field


class Query(BaseModel):
    sql: str = Field(..., description="One read-only SQLite query")


def executes_to_expected_rows(run, expected):
    sql = run.content.sql.strip()
    if not sql.lower().startswith(("select", "with")):
        return Score(0.0, False, reason="query must start with SELECT or WITH")

    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(expected["setup"])
        connection.execute("PRAGMA query_only = ON")
        actual = [list(row) for row in connection.execute(sql).fetchall()]
    except sqlite3.Error as exc:
        return Score(0.0, False, reason=f"SQLite rejected the query: {exc}")
    finally:
        connection.close()

    passed = actual == expected["rows"]
    return Score(1.0 if passed else 0.0, passed, reason=f"returned rows: {actual}")


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low", verbosity="low"),
    instructions=(
        "Return one read-only SQLite query. Follow every temporal rule literally. "
        "Do not assume facts not present in the schema."
    ),
    output_schema=Query,
)

setup = """
CREATE TABLE inventory_events (
    event_id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL,
    happened_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    qty INTEGER,
    reserve_event_id INTEGER
);
INSERT INTO inventory_events VALUES
    (1, 'A', '2025-01-01 09:00:00', 'receive', 10, NULL),
    (2, 'A', '2025-01-01 10:00:00', 'reserve', 7, NULL),
    (3, 'A', '2025-01-01 11:00:00', 'reserve', 5, NULL),
    (4, 'A', '2025-01-01 12:00:00', 'release', NULL, 2),
    (5, 'A', '2025-01-01 13:00:00', 'release', NULL, 2),
    (6, 'A', '2025-01-01 14:00:00', 'reserve', 10, NULL),
    (7, 'A', '2025-01-01 15:00:00', 'release', NULL, 3),
    (8, 'A', '2025-01-01 16:00:00', 'receive', 4, NULL),
    (10, 'B', '2025-01-01 09:00:00', 'receive', 5, NULL),
    (11, 'B', '2025-01-01 10:00:00', 'reserve', 6, NULL),
    (12, 'B', '2025-01-01 11:00:00', 'reserve', 3, NULL),
    (13, 'B', '2025-01-01 12:00:00', 'release', NULL, 12),
    (14, 'B', '2025-01-01 13:00:00', 'reserve', 4, NULL),
    (15, 'B', '2025-01-01 14:00:00', 'release', NULL, 999);
"""

prompt = """
Schema: inventory_events(event_id, sku, happened_at, kind, qty, reserve_event_id).

Replay events independently per SKU in happened_at, event_id order, starting with
stock=0. `receive` always adds qty. `reserve` is accepted only when current stock is at
least qty; an accepted reserve subtracts qty, while a rejected reserve changes no
stock. `release` is valid only when reserve_event_id names a previously accepted
reserve for the same SKU that has not already had a valid release. A valid release
adds the original reserve quantity and consumes that reserve; duplicate, rejected,
unknown, future, or cross-SKU references are invalid and change no stock.

Return sku, final_stock, accepted_reserves, rejected_reserves, valid_releases,
invalid_releases, ordered by sku. SQLite JSON functions are available if useful for
carrying accepted reservation ids and quantities through a recursive CTE. Use one
read-only SQLite query.
"""

env = Environment(
    name="inventory-state-sql",
    agent=agent,
    tasks=(
        Task(
            id="inventory-state",
            input=prompt,
            expected={
                "setup": setup,
                "rows": [["A", 4, 2, 1, 1, 2], ["B", 1, 2, 1, 1, 1]],
            },
        ),
    ),
    scorer=CodeScorer(executes_to_expected_rows),
)


if __name__ == "__main__":
    results = run_rollouts(env, k=8, concurrency=4)
    print(results)
    results.print_report()
