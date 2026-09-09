"""Allow documentation and preview browsers through a single public origin policy.

Set PAGE_DEMO_DB_URL and OPENAI_API_KEY before serving. --check performs no IO.
"""

import argparse
from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.public import PublicSurface

db = PostgresDb(
    db_url=getenv(
        "PAGE_DEMO_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/origin_demo"
    )
)
agent = Agent(id="docs", model=OpenAIResponses(id="gpt-5.6-luna"), db=db)
agent_os = AgentOS(
    id="browser-origin-demo",
    agents=[agent],
    db=db,
    public=PublicSurface(agents=[agent], enforce_browser_origins=True),
    cors_allowed_origins=["https://docs.example.com", "https://os.agno.com"],
    cors_allowed_origin_regex=r"https://docs-[a-z0-9-]+\.example\.com",
    cors_merge_base_app_origins=False,
)
app = agent_os.get_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    if parser.parse_args().check:
        print("Browser origin configuration validated.")
    else:
        agent_os.serve("browser_origins:app", host="127.0.0.1", port=8000, reload=False)
