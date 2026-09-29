"""
Expose one custom MCP tool
==========================

Replace the eight built-in AgentOS MCP tools with one purpose-built tool. The
tool routes a question through an agent while AgentOS owns the MCP transport,
mount, and lifespan.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/custom_tools.py
Try: connect an MCP client to http://localhost:7777/mcp and call ask_workspace
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create the custom tool
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="mcp-custom-tools-db",
    db_file="tmp/mcp_custom_tools.db",
)

workspace_agent = Agent(
    id="workspace-agent",
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer workspace questions clearly and concisely.",
)


@tool(
    name="ask_workspace",
    title="Ask the Workspace Agent",
    description="Ask the workspace agent a question",
    # A custom tool publishes whatever it declares here and nothing more, so state all
    # three hints: a client that finds one missing falls back to a protocol default,
    # and a directory submission is rejected outright for leaving any of them unset.
    # These are true of this tool: the run persists a session (not read-only), it only
    # appends (nothing destroyed), and the agent calls a model over the network.
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    },
)
async def ask_workspace(question: str) -> str:
    """Route one question through the workspace agent."""
    response = await workspace_agent.arun(question)
    return response.content or ""


# ---------------------------------------------------------------------------
# Serve only the custom tool
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="mcp-custom-tools-os",
    description="AgentOS exposing one purpose-built MCP tool.",
    db=db,
    agents=[workspace_agent],
    mcp=MCPConfig(
        tools=[ask_workspace],
        default_tools=False,
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Custom Tool AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
