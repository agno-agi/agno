"""
Callable Dependencies
=============================

Inject functions as dependencies. Each callable is invoked once at the start
of every run, so the agent always sees fresh data without you needing to
pass it explicitly.

Pitfall: callables run once per run, not per turn or per tool call. For
truly dynamic per-tool-call data, fetch it inside the tool instead.
"""

from datetime import datetime

from agno.agent import Agent
from agno.models.openai import OpenAIResponses


def get_current_time() -> str:
    return datetime.now().isoformat()


def get_active_users() -> list[dict]:
    # Pretend this is a database query that runs at the start of every run
    return [
        {"id": 1, "name": "Alice", "role": "admin"},
        {"id": 2, "name": "Bob", "role": "viewer"},
    ]


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    dependencies={
        "current_time": get_current_time,
        "active_users": get_active_users,
    },
    add_dependencies_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What time is it now and who is currently active in the system?"
    )
