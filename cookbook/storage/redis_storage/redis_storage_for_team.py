"""
1. Run: `pip install openai duckduckgo-search newspaper4k lxml_html_clean agno` to install the dependencies
2. Run: `python cookbook/storage/json_storage/json_storage_for_team.py` to run the team

We can start Redis locally using docker:
1. Start Redis container
docker run --name my-redis -p 6379:6379 -d redis

2. Verify container is running
docker ps
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.redis import RedisStorage
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel

storage = RedisStorage(prefix="agno_test", host="localhost", port=6379)


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
    add_datetime_to_instructions=True,
)


hn_team = Team(
    name="HackerNews Team",
    mode="coordinate",
    model=OpenAIChat("gpt-4o"),
    members=[hn_researcher, web_searcher],
    storage=storage,
    instructions=[
        "First, search hackernews for what the user is asking about.",
        "Then, ask the web searcher to search for each story to get more information.",
        "Finally, provide a thoughtful and engaging summary.",
    ],
    response_model=Article,
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
)

hn_team.print_response("Write an article about the top 2 stories on hackernews")
