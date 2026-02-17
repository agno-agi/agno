"""
Dynamic Tools
=============================

Dynamic Tools.
"""

from datetime import datetime

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run import RunContext


def get_runtime_tools(run_context: RunContext):
    """Return tools dynamically based on session state."""

    def get_time() -> str:
        return datetime.utcnow().isoformat()

    def get_project() -> str:
        project = (run_context.session_state or {}).get("project", "unknown")
        return f"Current project: {project}"

    return [get_time, get_project]


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Dynamic Tools Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=get_runtime_tools,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Use available tools to report current context.",
        session_state={"project": "cookbook-restructure"},
        stream=True,
    )
