"""
Serve a toolkit as MCP tools
============================

Pass a Toolkit to MCPConfig.tools and AgentOS flattens it into one MCP tool per
method, the way an agent takes it apart. MemoryTools becomes get_memories,
add_memory, update_memory, and delete_memory.

Every one of those methods declares `run_context: RunContext`. AgentOS keeps it
out of the client-facing schema -- pydantic cannot describe a RunContext, so a
visible one would stop the server from starting -- and fills it at call time
with a context carrying the authenticated caller. A client cannot claim to be
anyone else: the argument is not in the schema, and a value supplied for it is
rejected.

Who that caller is depends on the deployment. This example runs without an
authorization layer, so the resolved caller is None and every client shares one
memory bucket -- fine for a local lesson, wrong for anything shared. Add
`AgentOS(authorization=True, ...)` and the JWT subject becomes the memory owner;
see secure_mcp.py for the full configuration.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/toolkit_tools.py
Try: connect an MCP client to http://localhost:7777/mcp and call add_memory
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig
from agno.tools.memory import MemoryTools

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="mcp-toolkit-db",
    db_file="tmp/mcp_toolkit.db",
)

# ---------------------------------------------------------------------------
# Create the toolkit
# ---------------------------------------------------------------------------

# think and analyze are left off: both accumulate into the run's session_state,
# and an MCP tool call has no run behind it to accumulate into.
memory_tools = MemoryTools(
    db=db,
    enable_think=False,
    enable_analyze=False,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

memory_agent = Agent(
    id="memory-agent",
    name="Memory Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[memory_tools],
    instructions="Remember what the user tells you, and recall it on request.",
    add_history_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Serve the toolkit as the whole MCP surface
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="mcp-toolkit-os",
    description="AgentOS serving a memory toolkit as individual MCP tools.",
    db=db,
    agents=[memory_agent],
    mcp=MCPConfig(
        tools=[memory_tools],
        default_tools=False,
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Toolkit AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
