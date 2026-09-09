"""
Example showing how to use Valkey as the database for a team.

Run: `uv pip install ddgs valkey-glide-sync` to install the dependencies

We can start Valkey locally using docker:
1. Start Valkey container
`docker run --name my-valkey -p 6379:6379 -d valkey/valkey-bundle`

2. Verify container is running
`docker ps`

3. Run the file
`python cookbook/06_storage/valkey/valkey_for_team.py`
"""

from typing import List

from agno.agent import Agent
from agno.db.valkey import ValkeyDb
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = ValkeyDb()


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
class Article(BaseModel):
    title: str
    summary: str
    reference_links: List[str]


hn_researcher = Agent(
    name="HackerNews Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIResponses(id="gpt-5.5"),
    role="Searches the web for information on a topic",
    tools=[WebSearchTools()],
    add_datetime_to_context=True,
)


hn_team = Team(
    name="HackerNews Team",
    model=OpenAIResponses(id="gpt-5.5"),
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
