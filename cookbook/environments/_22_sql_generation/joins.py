"""
SQL Generation - Joins
======================

Join organizations, tickets, response history, SLA policy, and a holiday calendar.
The query must find the first valid human response and count only business minutes.
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
        "Return one read-only SQLite query. Use CTEs when they make the temporal "
        "rules explicit, and preserve the requested output ordering."
    ),
    output_schema=Query,
)

setup = """
CREATE TABLE organizations (
    org_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sla_minutes INTEGER NOT NULL
);
CREATE TABLE tickets (
    ticket_id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL,
    opened_at TEXT NOT NULL
);
CREATE TABLE responses (
    response_id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    actor_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE holidays (holiday_date TEXT PRIMARY KEY);
INSERT INTO organizations VALUES
    (1, 'Atlas', 120),
    (2, 'Boreal', 60),
    (3, 'Cygnus', 30);
INSERT INTO holidays VALUES ('2025-07-07');
INSERT INTO tickets VALUES
    (101, 1, '2025-07-04 16:30:00'),
    (102, 1, '2025-07-07 10:00:00'),
    (103, 1, '2025-07-08 16:30:00'),
    (201, 2, '2025-07-08 09:00:00'),
    (202, 2, '2025-07-08 16:45:00'),
    (301, 3, '2025-07-08 09:00:00');
INSERT INTO responses VALUES
    (1, 101, 'bot', '2025-07-04 16:31:00'),
    (2, 101, 'agent', '2025-07-07 10:00:00'),
    (3, 102, 'agent', '2025-07-08 10:30:00'),
    (4, 103, 'agent', '2025-07-09 12:00:00'),
    (5, 201, 'agent', '2025-07-08 08:55:00'),
    (6, 201, 'agent', '2025-07-08 10:00:00'),
    (7, 202, 'agent', '2025-07-09 09:46:00'),
    (8, 301, 'agent', '2025-07-08 09:20:00');
"""

prompt = """
Schemas:
- organizations(org_id, name, sla_minutes)
- tickets(ticket_id, org_id, opened_at)
- responses(response_id, ticket_id, actor_type, created_at)
- holidays(holiday_date)

For each organization with at least two tickets, return name, ticket_count,
within_sla_count, and within_sla_rate rounded to three decimals. A ticket's response
is its earliest actor_type='agent' response at or after opened_at; bot and pre-open
rows do not count. Tickets with no valid response fail SLA.

Elapsed time is BUSINESS MINUTES only: Monday-Friday, excluding dates in holidays,
from 09:00 inclusive to 17:00 exclusive. Define the count precisely as the number of
whole minute instants m with opened_at <= m < response_at that lie inside those
business periods. Compare that count to the organization's sla_minutes with <= as a
pass. A recursive minute calendar is acceptable. Order by within_sla_rate DESC, then
name ASC. Use one read-only SQLite query.
"""

env = Environment(
    name="joined-sla-sql",
    agent=agent,
    tasks=(
        Task(
            id="business-minute-sla",
            input=prompt,
            expected={
                "setup": setup,
                "rows": [["Atlas", 3, 2, 0.667], ["Boreal", 2, 1, 0.5]],
            },
        ),
    ),
    scorer=CodeScorer(executes_to_expected_rows),
)


if __name__ == "__main__":
    results = run_rollouts(env, k=8, concurrency=4)
    print(results)
    results.print_report()
