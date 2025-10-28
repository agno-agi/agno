r"""
Run SurrealDB in a container before running this script

```
docker run --rm --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root
```

or with

```
surreal start -u root -p root
```

Then:

1. Run: `pip install anthropic ddgs newspaper4k lxml_html_clean surrealdb agno` to install the dependencies
2. Run: `python cookbook/db/surrealdb/surrealdb_for_team.py` to run the team
"""

from typing import List

from agno.agent import Agent
from agno.db.surrealdb import SurrealDb
from agno.models.anthropic import Claude
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "agno"
SURREALDB_DATABASE = "surrealdb_for_team"

creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE)


class Article(BaseModel):
    title: str
    summary: str
    reference_links: List[str]


hn_researcher = Agent(
    name="HackerNews Researcher",
    model=Claude(id="claude-sonnet-4-5-20250929"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

web_searcher = Agent(
    name="Web Searcher",
    model=Claude(id="claude-sonnet-4-5-20250929"),
    role="Searches the web for information on a topic",
    tools=[DuckDuckGoTools()],
    add_datetime_to_context=True,
)


hn_team = Team(
    name="HackerNews Team",
    model=Claude(id="claude-sonnet-4-5-20250929"),
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

hn_team.print_response("Write an article about the top 2 stories on hackernews")
