"""
SQL Generation - Window Functions
=================================

Replay state-dependent inventory events, retain stock after every event, then find
each upward crossing of a stock threshold. The task combines recursive state with a
window comparison over the resulting trajectory.
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
        "Return one read-only SQLite query. Build the state trajectory first, then "
        "apply window logic to that retained trajectory."
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
    (9, 'A', '2025-01-01 17:00:00', 'receive', 2, NULL),
    (10, 'B', '2025-01-01 09:00:00', 'receive', 5, NULL),
    (11, 'B', '2025-01-01 10:00:00', 'reserve', 6, NULL),
    (12, 'B', '2025-01-01 11:00:00', 'reserve', 3, NULL),
    (13, 'B', '2025-01-01 12:00:00', 'release', NULL, 12),
    (14, 'B', '2025-01-01 13:00:00', 'reserve', 4, NULL),
    (15, 'B', '2025-01-01 14:00:00', 'release', NULL, 999),
    (16, 'B', '2025-01-01 15:00:00', 'receive', 5, NULL);
"""

prompt = """
Schema: inventory_events(event_id, sku, happened_at, kind, qty, reserve_event_id).

Replay events independently per SKU in happened_at, event_id order, starting with
stock=0. `receive` adds qty. `reserve` is accepted only when current stock >= qty; an
accepted reserve subtracts qty, a rejected reserve changes nothing. `release` is valid
only when reserve_event_id names a previously accepted reserve for the same SKU that
has not already had a valid release. A valid release restores the original reserve
quantity and consumes that reserve; duplicate, rejected, unknown, future, or cross-SKU
references change nothing.

Retain stock_after for every event and derive delta_stock as stock_after minus the
previous stock (zero before the first event). Return every event where stock_after >=
5 and the previous stock was < 5. Output sku, event_id, delta_stock, stock_after,
ordered by sku, happened_at, event_id. SQLite JSON functions are available for
recursive state and window functions are available for the crossing comparison. Use
one read-only SQLite query.
"""

final_state_prompt = """
Schema: inventory_events(event_id, sku, happened_at, kind, qty, reserve_event_id).

Replay events independently per SKU in happened_at, event_id order, starting with
stock=0. `receive` adds qty. Accept a `reserve` only when current stock >= qty and
subtract accepted qty. Accept a `release` only when its reference names a previously
accepted same-SKU reserve that no earlier valid release consumed; restore that
reserve's original qty. Rejected, duplicate, unknown, future, and cross-SKU references
change no stock. Return sku, final_stock, accepted_reserves, rejected_reserves,
valid_releases, invalid_releases ordered by sku. SQLite JSON functions are available.
Use one read-only SQLite query.
"""

env = Environment(
    name="inventory-crossing-sql",
    agent=agent,
    tasks=(
        Task(
            id="stateful-threshold-crossing",
            input=prompt,
            expected={
                "setup": setup,
                "rows": [
                    ["A", 1, 10, 10],
                    ["A", 4, 7, 10],
                    ["A", 9, 2, 6],
                    ["B", 10, 5, 5],
                    ["B", 13, 3, 5],
                    ["B", 16, 5, 6],
                ],
            },
        ),
        Task(
            id="final-state-audit",
            input=final_state_prompt,
            expected={
                "setup": setup,
                "rows": [["A", 6, 2, 1, 1, 2], ["B", 6, 2, 1, 1, 1]],
            },
        ),
    ),
    scorer=CodeScorer(executes_to_expected_rows),
)


if __name__ == "__main__":
    results = run_rollouts(env, k=8, concurrency=4)
    print(results)
    results.print_report()
