"""
AgentOS Platform Dashboard
==========================

Demonstrates an agent that charts real data instead of illustrative numbers.

Three worker agents on different models and tools generate traced activity for
several users, and their sessions are spread across the last seven days. A
dashboard agent then combines two toolkits: AgentOSTools reads the platform's
own metrics, run activity, and tool statistics from the database, and ChartTools
turns each result into a validated chart block. The agent chains the calls,
fetching the data first and charting it second, so every chart in Agno OS is
grounded in a tool result.

Seeding runs once on an empty database. Delete `tmp/agentos_platform_dashboard.db`
to reseed.

Prerequisites: export OPENAI_API_KEY=...
Run: .venvs/demo/bin/python cookbook/05_agent_os/chart_responses/agentos_platform_dashboard.py
Try: ask the Platform Dashboard "Chart token usage by day and the model mix."
"""

import time
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AgentOSConfig, ChatConfig
from agno.tools.agentos import AgentOSTools
from agno.tools.calculator import CalculatorTools
from agno.tools.chart import ChartTools
from sqlalchemy import text

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)

db = SqliteDb(
    id="platform-dashboard-db", db_file=str(DB_DIR / "agentos_platform_dashboard.db")
)

# ---------------------------------------------------------------------------
# Workers: three agents on different models and tools produce traced activity
# ---------------------------------------------------------------------------


def lookup_order(order_id: str) -> str:
    """Look up the status of a customer order.

    Args:
        order_id (str): The order identifier, for example "A-1042".

    Returns:
        str: The order status and estimated delivery date.
    """
    statuses = {
        "A-1042": "shipped, arriving 2026-10-17",
        "B-2210": "processing",
        "C-3307": "delivered",
    }
    return statuses.get(order_id, "order not found")


def lookup_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city (str): The city name.

    Returns:
        str: A short weather summary.
    """
    forecasts = {
        "Berlin": "12C, light rain",
        "Lisbon": "21C, sunny",
        "Tokyo": "18C, cloudy",
    }
    return forecasts.get(city, "no forecast available")


math_worker = Agent(
    id="math-worker",
    name="Math Worker",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[CalculatorTools()],
    instructions="Answer briefly. Use the calculator for any arithmetic.",
)

support_worker = Agent(
    id="support-worker",
    name="Support Worker",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[lookup_order],
    instructions="Answer briefly. Always look the order up before answering.",
)

travel_worker = Agent(
    id="travel-worker",
    name="Travel Worker",
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    tools=[lookup_weather],
    instructions="Answer briefly. Always check the weather before answering.",
)

# (worker, prompt, user, days ago). Spread across agents, users, and days so
# every chart has more than one bar, slice, or point.
SEED_RUNS = [
    (math_worker, "What is 41 * 73?", "ada", 6),
    (support_worker, "Where is order A-1042?", "grace", 6),
    (math_worker, "What is 12 + 30?", "linus", 5),
    (travel_worker, "What is the weather in Berlin?", "ada", 5),
    (support_worker, "Has order C-3307 arrived?", "grace", 4),
    (math_worker, "What is 2 ** 10?", "ada", 3),
    (travel_worker, "Should I pack an umbrella for Lisbon?", "linus", 3),
    (support_worker, "What is happening with order B-2210?", "ada", 2),
    (math_worker, "What is 1234 / 8?", "grace", 2),
    (travel_worker, "How warm is Tokyo right now?", "grace", 1),
    (math_worker, "What is 15% of 240?", "linus", 1),
    (support_worker, "Where is order A-1042 now?", "linus", 0),
]

# ---------------------------------------------------------------------------
# Dashboard: reads platform data with AgentOSTools, charts it with ChartTools
# ---------------------------------------------------------------------------

dashboard_agent = Agent(
    id="platform-dashboard",
    name="Platform Dashboard",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[AgentOSTools(db=db), ChartTools()],
    instructions=[
        "You build visual reports about this AgentOS deployment.",
        "Always fetch data with an AgentOSTools call before creating a chart. Never invent numbers.",
        "Pick the chart from the shape of the data:",
        "- daily token usage: bar chart of total tokens per date",
        "- runs or sessions over time: line chart keyed by date",
        "- model mix or share of runs: pie chart keyed by model",
        "- per-agent latency or tool duration: bar-horizontal sorted by value",
        "Use the date strings and metric names exactly as the tool returned them.",
        "If a window has no data, say so instead of charting an empty series.",
        "Mention the time window and any backend notes the tool included.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    id="platform-dashboard-demo",
    description="AgentOS cookbook for charting live platform metrics in Agno OS.",
    # Only the dashboard is served. The workers exist to seed activity; tracing
    # is process-wide, so their runs are captured without registering them.
    agents=[dashboard_agent],
    db=db,
    tracing=True,
    config=AgentOSConfig(
        chat=ChatConfig(
            quick_prompts={
                "platform-dashboard": [
                    "Chart token usage by day and the model mix.",
                    "Show runs per agent for the last 7 days with average latency.",
                    "Which tools were used most and how long did they take?",
                ],
            },
        ),
    ),
)
app = agent_os.get_app()


def seed_activity() -> None:
    """Run the workers once on an empty database so the dashboard has a week of activity."""
    if db.get_sessions(limit=1):
        print("Database already has sessions, skipping seed.")
        return

    print(f"Seeding {len(SEED_RUNS)} worker runs across the last 7 days.")
    for index, (worker, prompt, user_id, days_ago) in enumerate(SEED_RUNS):
        session_id = f"seed-{index}"
        worker.run(prompt, session_id=session_id, user_id=user_id)
        # The metrics rollup buckets sessions by created_at, so backdating the
        # session spreads the daily chart across the week. Traces keep real times.
        created_at = int(time.time()) - days_ago * 86400
        with db.db_engine.begin() as conn:
            conn.execute(
                text(
                    f"UPDATE {db.session_table_name} SET created_at = :ts WHERE session_id = :sid"
                ),
                {"ts": created_at, "sid": session_id},
            )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed_activity()
    agent_os.serve(app="agentos_platform_dashboard:app", port=7777)
