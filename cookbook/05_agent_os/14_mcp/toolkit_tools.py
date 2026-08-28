"""
Expose a Toolkit as MCP tools
=============================

Pass a Toolkit to MCPServerConfig.tools — it auto-flattens into individual
MCP tools, same as Agent.parse_tools() does internally. The Workspace toolkit
becomes read_file, list_files, search_content, and grep_content.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/toolkit_tools.py
Try: connect an MCP client to http://localhost:7777/mcp and call read_file
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPServerConfig
from agno.tools.workspace import Workspace

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="mcp-toolkit-db",
    db_file="tmp/mcp_toolkit.db",
)

# ---------------------------------------------------------------------------
# Create Toolkit
# ---------------------------------------------------------------------------

workspace = Workspace(
    root=".",
    allowed=["read", "list", "search", "grep"],
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

workspace_agent = Agent(
    id="workspace-agent",
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[workspace],
    instructions="Help users explore and understand the workspace files.",
    add_history_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS with Toolkit as MCP tools
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="mcp-toolkit-os",
    description="AgentOS exposing Workspace toolkit as individual MCP tools.",
    db=db,
    agents=[workspace_agent],
    mcp_server=MCPServerConfig(
        tools=[workspace],
        enable_builtin_tools=False,
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
