"""
1. Run: `pip install openai ddgs newspaper4k lxml_html_clean agno` to install the dependencies
2. Run: `python cookbook/storage/in_memory_storage/in_memory_storage_for_team.py` to run the team
"""

from typing import List

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel


class Article(BaseModel):
    title: str
    summary: str
    reference_links: List[str]


hn_researcher = Agent(
    name="HackerNews Researcher",
    model=OpenAIChat("gpt-4o"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a topic",
    tools=[DuckDuckGoTools()],
)

# Setup the in-memory database
db = InMemoryDb()

# Setup the team and pass the database
hn_team = Team(
    name="HackerNews Team",
    model=OpenAIChat("gpt-4o"),
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
