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
from agno.models.openai import OpenAIChat
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
db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE, session_table="agno_sessions_team")


class Article(BaseModel):
    title: str
    summary: str
    reference_links: List[str]


hn_researcher = Agent(
    id="hn_researcher",
    name="HackerNews Researcher",
    model=OpenAIChat(id="gpt-4o"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

web_searcher = Agent(
    id="web_searcher",
    name="Web Searcher",
    model=OpenAIChat(id="gpt-4o"),
    role="Searches the web for information on a topic",
    tools=[DuckDuckGoTools()],
    add_datetime_to_context=True,
)


hn_team = Team(
    id="hn_team",
    name="HackerNews Team",
    model=OpenAIChat(id="gpt-4o"),
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
    add_history_to_context=True,
)

hn_team.print_response("Write an article about the top 2 stories on hackernews", stream=True)
