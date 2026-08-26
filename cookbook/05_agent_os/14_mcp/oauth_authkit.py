"""
Use WorkOS AuthKit for MCP OAuth
================================

Keep AgentOS as the MCP resource server while WorkOS AuthKit owns login,
consent, and token issuance. Configure AuthKit to issue AgentOS resource
scopes such as ``config:read`` and ``agents:run``.

Prerequisites: OPENAI_API_KEY, AUTHKIT_DOMAIN, and public AGENTOS_URL
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/oauth_authkit.py
Try: Inspect GET /.well-known/oauth-protected-resource/mcp
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from fastmcp.server.auth.providers.workos import AuthKitProvider

# ---------------------------------------------------------------------------
# Create an AuthKit-protected AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="mcp-oauth-authkit-db",
    db_file="tmp/mcp_oauth_authkit.db",
)

authkit_agent = Agent(
    id="authkit-assistant",
    name="AuthKit Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer authenticated users concisely.",
)

mcp_auth = AuthKitProvider(
    authkit_domain=os.environ["AUTHKIT_DOMAIN"],
    base_url=os.environ["AGENTOS_URL"],
)

agent_os = AgentOS(
    id="mcp-oauth-authkit-os",
    description="AgentOS using WorkOS AuthKit for MCP OAuth.",
    db=db,
    agents=[authkit_agent],
    mcp_server=True,
    mcp_auth=mcp_auth,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AuthKit AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
