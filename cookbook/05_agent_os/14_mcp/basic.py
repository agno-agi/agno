"""
Serve AgentOS over MCP
======================

Expose one agent through the eight built-in AgentOS MCP tools at ``/mcp``.
The confirmation-required tool gives the companion ``mcp_client.py`` a real
PAUSED run to continue or cancel.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/basic.py
Try: in another terminal, run mcp_client.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create an MCP-enabled AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="mcp-basic-db",
    db_file="tmp/mcp_basic.db",
)


@tool(requires_confirmation=True)
def restart_service(service: str) -> str:
    """Restart a service after the caller confirms the action."""
    return f"Restarted {service}"


operations_agent = Agent(
    id="operations-agent",
    name="Operations Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[restart_service],
    instructions=(
        "When asked to restart a service, call restart_service immediately. "
        "Do not ask for confirmation in chat because the tool enforces it."
    ),
    add_history_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    id="mcp-basic-os",
    description="AgentOS exposed through the built-in MCP operator tools.",
    db=db,
    agents=[operations_agent],
    mcp_server=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
