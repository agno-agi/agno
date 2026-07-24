"""AgentOS with OAuth on the MCP endpoint — the built-in authorization server (Tier 1).

claude.ai and ChatGPT connect to a custom MCP server over OAuth only; there is no field
to paste a bearer token. This makes AgentOS its own OAuth authorization server, so those
clients connect by pasting the /mcp URL — no external accounts. The endpoint is never
open: connecting requires the deployer secret on a consent page.

Setup:

    export AGENTOS_URL=https://your-deployment.example.com   # the public origin
    export MCP_CONNECT_SECRET=$(openssl rand -base64 32)            # the login secret (>= 16 chars)
    export AGENTOS_MCP_SIGNING_KEY=$(openssl rand -base64 32)       # optional: env-pinned token key (>= 32 chars)

AGENTOS_URL must be the public origin the client actually connects to (every advertised
OAuth URL and the token audience derive from it) -- so behind a tunnel or proxy, set it to
the external HTTPS URL, not localhost. AGENTOS_MCP_SIGNING_KEY is optional but recommended
in production: set it so the token trust root is env-managed and survives redeploys / is
shared across replicas; when unset, a key is generated and persisted in the database.

Then, in claude.ai (Settings -> Connectors) or ChatGPT (custom connector), paste your
public /mcp URL, sign in with the connect secret on the consent page, and connect.

Requires a Postgres database (the built-in server stores clients, codes, and refresh-token
state there). Run one with: ./cookbook/scripts/run_pgvector.sh
"""

import os

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.os import AgentOS, AgentOSBuiltinAuth
from agno.tools.websearch import WebSearchTools

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

web_research_agent = Agent(
    id="web-research-agent",
    name="Web Research Agent",
    model=Claude(id="claude-sonnet-4-5"),
    db=db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
    markdown=True,
)

# AgentOSBuiltinAuth makes this AgentOS its own OAuth server; it binds to the Postgres db
# passed to AgentOS below. Existing agno_pat_ and JWT clients keep working alongside it.
# The inputs are spelled out here so the example documents itself; the shorthand
# AgentOSBuiltinAuth.from_env() reads these same env vars.
mcp_auth = AgentOSBuiltinAuth(
    url=os.environ["AGENTOS_URL"],
    secret=os.environ["MCP_CONNECT_SECRET"],
    signing_key_material=os.environ.get("AGENTOS_MCP_SIGNING_KEY"),
)

agent_os = AgentOS(
    description="Example app with OAuth on the MCP endpoint",
    agents=[web_research_agent],
    db=db,
    mcp_server=True,
    mcp_auth=mcp_auth,
)

app = agent_os.get_app()

if __name__ == "__main__":
    """Run your AgentOS.

    Deploy behind HTTPS at AGENTOS_URL, then add the /mcp URL as a custom
    connector in claude.ai or ChatGPT.
    """
    agent_os.serve(app="oauth_builtin_example:app")
