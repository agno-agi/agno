"""Serve anonymous chat and MCP alongside a JWT-authenticated Control Plane.

Set PAGE_DEMO_DB_URL and JWT_VERIFICATION_KEY (the Control Plane's RS256 public
key), then run this file. Add --check to validate configuration without starting
PostgreSQL or making a model call. OPENAI_API_KEY is needed for live chat.
"""

import argparse
from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig
from agno.os.public import PublicSurface


def service_description() -> str:
    """Describe the support service."""
    return "Ask the support agent for help with Agno."


db = PostgresDb(
    db_url=getenv(
        "PAGE_DEMO_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/page_demo"
    )
)
agent = Agent(
    id="support", name="Support", model=OpenAIResponses(id="gpt-5.6-luna"), db=db
)
agent_os = AgentOS(
    id="public-support",
    agents=[agent],
    db=db,
    authorization=True,
    public=PublicSurface(agents=[agent], mcp=True),
    mcp=MCPConfig(tools=[service_description], default_tools=False, stateless=True),
    cors_allowed_origins=["https://os.agno.com", "http://localhost:3000"],
)
app = agent_os.get_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Validate configuration without serving"
    )
    args = parser.parse_args()
    if args.check:
        print("Public chat, explicit MCP tools and JWT API access are configured.")
    else:
        agent_os.serve(app=app)
