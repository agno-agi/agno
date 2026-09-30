"""Use Oracle Database as the storage backend for a Team.

Requires Oracle Database 19c or later. Start one locally with:
    ./cookbook/scripts/run_oracle.sh

Run `uv pip install "agno[oracle]" openai ddgs newspaper4k lxml_html_clean` to install dependencies.
"""

from typing import List

from agno.agent import Agent
from agno.db.oracle import OracleDb
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# On Oracle a schema is a user, so tables are created in the connecting
# user's own schema by default. See the README for how db_schema and
# create_schema behave differently here than on Postgres.
db = OracleDb(db_url="oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1")


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
class Article(BaseModel):
    title: str
    summary: str
    reference_links: List[str]


hn_researcher = Agent(
    name="HackerNews Researcher",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    role="Searches the web for information on a topic",
    tools=[WebSearchTools()],
    add_datetime_to_context=True,
)

hn_team = Team(
    name="HackerNews Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[hn_researcher, web_searcher],
    db=db,
    instructions=[
        "First, search hackernews for what the user is asking about.",
        "Then, ask the web searcher to search for each story to get more information.",
        "Finally, provide a thoughtful and engaging summary.",
    ],
    output_schema=Article,
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    hn_team.print_response("Write an article about the top 2 stories on hackernews")
