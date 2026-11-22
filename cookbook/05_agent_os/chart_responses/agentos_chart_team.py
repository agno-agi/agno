"""
AgentOS Chart Team
==================

Demonstrates a Team whose members each render inline charts with ChartTools and
whose leader assembles them into one report.

Each member owns one view of the data and the tool that reads it: the Usage
Analyst charts activity trends from `get_daily_usage`, the Cost Analyst charts
spend from `get_spend_by_model`. The leader delegates to both and returns a
single response that keeps every member chart block verbatim, so Agno OS renders
a multi-chart report from one team run.

The data tools return a fixed sample dataset so the example runs without a
database. Swap them for your own warehouse or billing queries.

Prerequisites: export OPENAI_API_KEY=...
Run: .venvs/demo/bin/python cookbook/05_agent_os/chart_responses/agentos_chart_team.py
Try: ask the Growth Review Team "Review the last 30 days of usage and cost."
"""

import json
from datetime import date, timedelta

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AgentOSConfig, ChatConfig
from agno.team import Team
from agno.tools.chart import ChartTools

db = SqliteDb(db_file="tmp/agentos_chart_team.db")

# ---------------------------------------------------------------------------
# Data tools: fixed sample data standing in for your usage and billing queries
# ---------------------------------------------------------------------------

MODELS = {"gpt-5.6-luna": 0.62, "claude-sonnet-5-5": 0.28, "gemini-3-flash": 0.10}
INPUT_PRICE_PER_1K = 0.0025
OUTPUT_PRICE_PER_1K = 0.01


def get_daily_usage(days: int = 30) -> str:
    """Get daily platform activity: runs, sessions, and active users per day.

    Args:
        days (int): Number of days to include, counting back from today. Defaults to 30.

    Returns:
        str: JSON list of {date, runs, sessions, active_users} rows, oldest first.
    """
    days = max(1, min(days, 90))
    today = date.today()
    rows = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        growth = days - offset
        weekend_dip = 0.6 if day.weekday() >= 5 else 1.0
        runs = int((180 + growth * 9) * weekend_dip)
        rows.append(
            {
                "date": day.isoformat(),
                "runs": runs,
                "sessions": int(runs * 0.55),
                "active_users": int(runs * 0.2),
            }
        )
    return json.dumps(rows)


def get_spend_by_model(days: int = 30) -> str:
    """Get token usage and estimated spend per model over a window.

    Args:
        days (int): Number of days to include, counting back from today. Defaults to 30.

    Returns:
        str: JSON with {window_days, total_cost_usd, models: [{model, input_tokens, output_tokens, cost_usd}]}.
    """
    days = max(1, min(days, 90))
    total_runs = sum(row["runs"] for row in json.loads(get_daily_usage(days)))
    models = []
    total_cost = 0.0
    for model, share in MODELS.items():
        runs = total_runs * share
        input_tokens = int(runs * 1800)
        output_tokens = int(runs * 420)
        cost = (input_tokens / 1000) * INPUT_PRICE_PER_1K + (
            output_tokens / 1000
        ) * OUTPUT_PRICE_PER_1K
        total_cost += cost
        models.append(
            {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost, 2),
            }
        )
    return json.dumps(
        {
            "window_days": days,
            "total_cost_usd": round(total_cost, 2),
            "models": models,
        }
    )


# ---------------------------------------------------------------------------
# Members: each one owns a view of the data and renders it as a chart
# ---------------------------------------------------------------------------

usage_analyst = Agent(
    id="usage-analyst",
    name="Usage Analyst",
    role="Chart activity trends: runs, sessions, and active users over time.",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[get_daily_usage, ChartTools()],
    instructions=[
        "Call get_daily_usage before charting. Never invent numbers.",
        "Prefer line or area charts for trends over time, keyed by date.",
        "Use one chart per question and keep the data under 31 rows.",
    ],
    markdown=True,
)

cost_analyst = Agent(
    id="cost-analyst",
    name="Cost Analyst",
    role="Chart spend: token usage and cost broken down by model or provider.",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[get_spend_by_model, ChartTools()],
    instructions=[
        "Call get_spend_by_model before charting. Never invent numbers.",
        "Use stacked bars to compare input and output tokens across models.",
        "Use a pie chart for share of spend by model.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Team: delegates to both members and assembles one multi-chart report
# ---------------------------------------------------------------------------

growth_review_team = Team(
    id="growth-review-team",
    name="Growth Review Team",
    description="Reviews platform usage and cost with one chart per member.",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    members=[usage_analyst, cost_analyst],
    instructions=[
        "Delegate activity questions to the Usage Analyst and spend questions to the Cost Analyst.",
        "Include every fenced chart block returned by a member verbatim. Never rewrite or summarize the JSON.",
        "Add a short heading above each chart naming the member's view.",
        "Close with a three-bullet summary that ties usage to cost.",
    ],
    delegate_to_all_members=True,
    show_members_responses=True,
    markdown=True,
)

agent_os = AgentOS(
    id="chart-team-demo",
    description="AgentOS cookbook for a Team that renders multi-chart reports in Agno OS.",
    teams=[growth_review_team],
    config=AgentOSConfig(
        chat=ChatConfig(
            quick_prompts={
                "growth-review-team": [
                    "Review the last 30 days of usage and cost.",
                    "Which model is driving most of our token spend this week?",
                    "Are daily active users growing faster than cost?",
                ],
            },
        ),
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="agentos_chart_team:app", port=7777, reload=True)
