"""Platform Ops Agent
==================

Give an agent a read-only ops view of the AgentOS it runs on with AgentOSTools.
A worker agent generates real traced activity, then an ops agent reads usage,
latency and tool statistics back from the same database and answers questions
about the platform.

AgentOSTools takes the database, never the AgentOS instance: agents are built
before the OS, so every tool reads only from db.

Prerequisites: export OPENAI_API_KEY=...
Run: .venvs/demo/bin/python cookbook/05_agent_os/25_agentos_tools/platform_ops_agent.py
Try: ask the ops agent "Which tool was slowest today?" or "How many runs failed?"
"""

import json
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.agentos import AgentOSTools
from agno.tools.calculator import CalculatorTools

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)

db = SqliteDb(id="platform-ops-db", db_file=str(DB_DIR / "platform_ops.db"))

# ---------------------------------------------------------------------------
# A worker agent that produces traced activity
# ---------------------------------------------------------------------------

worker = Agent(
    id="research-worker",
    name="Research Worker",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[CalculatorTools()],
    instructions="Answer briefly. Use the calculator for any arithmetic.",
    db=db,
)

# ---------------------------------------------------------------------------
# The ops agent that answers questions about the platform
# ---------------------------------------------------------------------------

ops_agent = Agent(
    id="platform-ops",
    name="Platform Ops",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[AgentOSTools(db=db)],
    instructions=[
        "You answer operations questions about this AgentOS deployment.",
        "Ground every number in a tool result and mention the time window.",
    ],
    db=db,
    markdown=True,
)

agent_os = AgentOS(
    id="platform-ops-os",
    name="Platform Ops AgentOS",
    description="AgentOS with a worker agent and a read-only platform ops agent.",
    agents=[worker, ops_agent],
    db=db,
    tracing=True,
)
app = agent_os.get_app()


def run_demo() -> None:
    # Generate traced activity for the ops agent to report on
    worker.run("What is 41 * 73?", session_id="ops-demo-session", user_id="demo-user")
    worker.run("What is 12 + 30?", session_id="ops-demo-session", user_id="demo-user")

    # Verify the platform data is visible through the toolkit before asking the agent
    toolkit = AgentOSTools(db=db)

    activity = json.loads(toolkit.get_run_activity(days=1))
    worker_rows = [
        row for row in activity["agents"] if row["agent_id"] == "research-worker"
    ]
    if not worker_rows or worker_rows[0]["total_traces"] < 2:
        raise RuntimeError(
            f"Expected at least 2 worker traces, got: {activity['agents']}"
        )
    print("Run activity:", worker_rows[0]["total_traces"], "worker traces,")
    print("  avg duration:", worker_rows[0]["avg_duration_ms"], "ms")

    tools = json.loads(toolkit.get_tool_activity(days=1))
    tool_names = [row["name"] for row in tools["tools_most_used"]]
    print("Tools used:", tool_names)

    metrics = json.loads(toolkit.get_platform_metrics(days=1))
    if metrics["totals"]["agent_sessions"] < 1:
        raise RuntimeError(
            f"Expected at least 1 agent session in metrics, got: {metrics['totals']}"
        )
    print("Sessions today:", metrics["totals"]["agent_sessions"])
    print("Tokens today:", metrics["totals"]["total_tokens"])

    # Now let the ops agent answer from the same data
    ops_agent.print_response(
        "Summarize activity on this platform: how many runs, by which agents, "
        "which tools were used, and how many tokens were spent."
    )


if __name__ == "__main__":
    run_demo()
