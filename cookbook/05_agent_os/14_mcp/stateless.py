"""
Serve AgentOS over MCP without session state
============================================

``MCPConfig(default_tools=True, stateless=True)`` serves the default tools
without transport sessions, including for legacy clients (2025-11-25 and earlier).
Modern requests (2026-07-28) are always sessionless, regardless of this flag.

Legacy stateless mode loses server-to-client requests and SSE resumability.
Request-scoped progress still works. Agno conversation history is independent;
multiple workers still need shared application storage and run coordination.
This SQLite example is for local development.

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
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions="Answer questions clearly and concisely.",
)

agent_os = AgentOS(
    id="mcp-stateless-os",
    description="AgentOS exposed over MCP with no session between requests.",
    db=db,
    agents=[stateless_agent],
    # Also disable transport sessions for clients using older protocol versions.
    mcp=MCPConfig(default_tools=True, stateless=True),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Stateless AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
