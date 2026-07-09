"""AgentOS with OAuth on the MCP endpoint — bring-your-own authorization server (Tier 2).

For production / multi-user: instead of the built-in server, pass any fastmcp AuthProvider.
WorkOS AuthKit is the documented default (free to 1M MAU) and gives real per-user
identity, RBAC, and SSO. The same mcp_auth seam carries both tiers, so this is a config
change, not a rewrite.

One-time WorkOS setup (free):
  1. Create an AuthKit project; enable Dynamic Client Registration.
  2. Register your public /mcp URL as a Resource Indicator (the token audience the log
     line below prints on startup).
  3. Set AUTHKIT_DOMAIN to your AuthKit domain.
  4. Configure AuthKit to emit agno-format scopes in the token's `scope`/`scp` claim:
     agents:run, teams:run, workflows:run, sessions:read, config:read (or whatever
     subset each user should have). AgentOS enforces its scope map on the external
     token, so a token carrying only OIDC scopes (openid/profile/email) authenticates
     but is denied every tool. Mapping users to agno scopes at the AS *is* the Tier-2
     per-user RBAC story.

    export AUTHKIT_DOMAIN=your-tenant.authkit.app
    export AGENTOS_URL=https://your-deployment.example.com

Then paste the /mcp URL into claude.ai or ChatGPT: they discover AuthKit as the
authorization server and run the OAuth flow against it — agno never sees a client secret.
"""

import os

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.websearch import WebSearchTools
from fastmcp.server.auth.providers.workos import AuthKitProvider

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

web_research_agent = Agent(
    id="web-research-agent",
    name="Web Research Agent",
    model=Claude(id="claude-sonnet-4-5"),
    db=db,
    tools=[WebSearchTools()],
    markdown=True,
)

# Any fastmcp AuthProvider works here; AuthKit is the documented default. Its AS endpoints
# live on the AuthKit domain, so agno only advertises it as the authorization server and
# verifies the tokens it issues.
mcp_auth = AuthKitProvider(
    authkit_domain=os.environ["AUTHKIT_DOMAIN"],
    base_url=os.environ["AGENTOS_URL"],
)

agent_os = AgentOS(
    description="Example app with WorkOS AuthKit on the MCP endpoint",
    agents=[web_research_agent],
    db=db,
    mcp_server=True,
    mcp_auth=mcp_auth,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="oauth_authkit_example:app")
