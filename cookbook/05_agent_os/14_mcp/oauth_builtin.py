"""
Use the built-in MCP authorization server
=========================================

Make AgentOS its own OAuth 2.1 authorization server for MCP connector clients.
The synchronous OS-level SQLite database stores clients, codes, signing keys,
and refresh tokens for local development; use synchronous PostgresDb for a
restart-safe, multi-replica production deployment.

Prerequisites: OPENAI_API_KEY, AGENTOS_URL, and MCP_CONNECT_SECRET (16+ chars)
Optional: AGENTOS_MCP_SIGNING_KEY (32+ high-entropy chars)
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/oauth_builtin.py
Try: Inspect GET /.well-known/oauth-protected-resource/mcp
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, AgentOSBuiltinAuth

# ---------------------------------------------------------------------------
# Create an OAuth-enabled AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="mcp-oauth-builtin-db",
    db_file="tmp/mcp_oauth_builtin.db",
)

oauth_agent = Agent(
    id="oauth-assistant",
    name="OAuth Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer authenticated connector users concisely.",
)

agent_os = AgentOS(
    id="mcp-oauth-builtin-os",
    description="AgentOS with its built-in MCP OAuth authorization server.",
    db=db,
    agents=[oauth_agent],
    mcp_server=True,
    mcp_auth=AgentOSBuiltinAuth.from_env(),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run OAuth AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
