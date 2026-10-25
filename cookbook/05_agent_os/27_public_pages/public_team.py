"""Serve a selected Team publicly; member routes remain private.

Run: .venvs/demo/bin/python cookbook/05_agent_os/27_public_pages/public_team.py
Requires PAGE_DEMO_DB_URL and OPENAI_API_KEY. Add --check to validate wiring only.
"""

import argparse
from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.public import PublicSurface
from agno.team import Team

# Reuse the member across runs; selecting the Team does not select its members.
db = PostgresDb(
    db_url=getenv(
        "PAGE_DEMO_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/page_demo"
    )
)
member = Agent(
    id="researcher", name="Researcher", model=OpenAIResponses(id="gpt-5.6-luna")
)
team = Team(
    id="support",
    name="Support",
    members=[member],
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
)
agent_os = AgentOS(
    id="public-support", db=db, teams=[team], public=PublicSurface(teams=[team])
)
app = agent_os.get_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration without serving or calling a model",
    )
    args = parser.parse_args()
    if args.check:
        print("Selected Team configuration is valid.")
    else:
        agent_os.serve(app=app)
