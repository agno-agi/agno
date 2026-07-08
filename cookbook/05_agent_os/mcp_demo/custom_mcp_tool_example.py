"""
AgentOS app that exposes ONE custom MCP tool routed through an agent, with the
built-in MCP tools disabled and the server gated to its owner.

This is the "one tool" shape: instead of the 8 built-in AgentOS tools, the MCP
server at /mcp exposes a single purpose-built tool that routes the caller's
question through a dedicated agent. Useful when you want to expose an AgentOS
agent as a single, well-scoped, owner-only MCP tool for another product to call.

It demonstrates everything that makes a custom MCP server clean to write -- no
hand-rolled middleware classes required:
  - `tools=[...]` + `enable_builtin_tools=False`: ship only your tool.
  - injected `user_id`: declare a `user_id` parameter and AgentOS fills it with the
    authenticated caller's id (the JWT subject) and hides it from the client schema,
    so callers cannot spoof it.
  - `authorize=...`: a per-call gate that 401s non-owners before the model runs.
  - `allowed_hosts=...`: built-in DNS-rebinding protection for an always-on local
    server (localhost works out of the box; list only your deploy/tunnel host).

After starting this app, point an MCP client at http://localhost:7777/mcp and
call the `ask_workspace` tool.
"""

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

# The set of owner identities allowed to use the server. In production these are
# the JWT subjects of your owners; AgentOS resolves the caller from the verified token.
OWNER_IDS = {"owner@example.com"}

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
async def ask_workspace(question: str, user_id: str) -> str:
    """Route a question through the workspace agent.

    `user_id` is injected by AgentOS from the authenticated request and is not part
    of the client-facing tool schema, so the agent always runs as the real caller.
    """
    response = await workspace_agent.arun(question, user_id=user_id)
    return response.content or ""


# ---------------------------------------------------------------------------
# Setup our AgentOS, exposing ONLY the custom tool on the MCP server
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    description="AgentOS exposing a single owner-only custom MCP tool",
    agents=[workspace_agent],
    enable_mcp_server=True,
    mcp_config=MCPServerConfig(
        tools=[ask_workspace],  # register our custom tool
        enable_builtin_tools=False,  # ship ONLY our tool (disable the 8 built-ins)
        # owner-only: 401 before the model runs
        authorize=lambda user_id: user_id in OWNER_IDS,
        # DNS-rebinding protection; localhost is allowed out of the box, add your deploy host
        allowed_hosts=["my-context.example.com"],
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
