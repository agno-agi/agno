"""
Serve AgentOS over MCP without session state
============================================

``MCPConfig(stateless=True)`` gives every request its own transport and keeps
nothing between requests, so any replica can answer any request and a
multi-instance deployment needs no session affinity.

The trade is whatever needs a retained session: server-initiated notifications
and SSE resumability. Tool calls do not, so a tool server loses nothing.

Run: python cookbook/05_agent_os/14_mcp/stateless.py
Connect an MCP client to http://localhost:7777/mcp; the responses carry no
     mcp-session-id header
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig

# ---------------------------------------------------------------------------
# Create a stateless MCP-enabled AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="mcp-stateless-db",
    db_file="tmp/mcp_stateless.db",
)

stateless_agent = Agent(
    id="stateless-agent",
    name="Stateless Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer questions clearly and concisely.",
)

agent_os = AgentOS(
    id="mcp-stateless-os",
    description="AgentOS exposed over MCP with no session between requests.",
    db=db,
    agents=[stateless_agent],
    # Leave this off (the default) when the server has to push notifications to a
    # client or resume an interrupted stream, since both need a retained session.
    mcp=MCPConfig(stateless=True),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Stateless AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
