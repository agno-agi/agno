"""
AgentOS app that exposes ONE custom MCP tool routed through an agent, with the
built-in MCP tools disabled.

This is the "one tool" shape: instead of the ~19 built-in AgentOS tools, the MCP
server at /mcp exposes a single purpose-built tool that routes the caller's
question through a dedicated agent. This is useful when you want to expose an
AgentOS agent as a single, well-scoped MCP tool for another product to call.

After starting this app, point an MCP client at http://localhost:7777/mcp and
call the `ask_workspace` tool. The built-in tools (run_agent, session/memory
CRUD, etc.) are not registered.
"""

from typing import Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import MCPServerConfig
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# Setup the database
db = SqliteDb(db_file="tmp/agentos.db")

# The agent that the single MCP tool routes through.
workspace_agent = Agent(
    id="workspace-agent",
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer questions about the user's workspace. Be concise.",
    markdown=True,
)


@tool(
    name="ask_workspace",
    description="Ask the workspace agent a question and get an answer",
)
async def ask_workspace(question: str, user_id: Optional[str] = None) -> str:
    """Route a question through the workspace agent.

    Passing user_id through means the agent can apply any per-user gating. The
    built-in run_agent tool resolves user_id from the authenticated request
    automatically; a custom tool decides for itself how to handle identity.
    """
    response = await workspace_agent.arun(question, user_id=user_id)
    return response.content or ""


# ---------------------------------------------------------------------------
# Setup our AgentOS, exposing ONLY the custom tool on the MCP server
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    description="AgentOS exposing a single custom MCP tool",
    agents=[workspace_agent],
    enable_mcp_server=True,
    mcp_config=MCPServerConfig(
        tools=[ask_workspace],  # register our custom tool
        enable_builtin_tools=False,  # ship ONLY our tool (disable the ~19 built-ins)
    ),
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    Your single-tool MCP server is served at:
    http://localhost:7777/mcp

    """
    agent_os.serve(app="custom_mcp_tool_example:app")
