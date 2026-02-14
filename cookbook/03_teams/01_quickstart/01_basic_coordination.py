"""
Basic Coordination
=============================

Demonstrates coordinated team workflows for both sync and async execution patterns.
"""

import asyncio
from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.newspaper4k import Newspaper4kTools
from agno.tools.websearch import WebSearchTools
from pydantic import BaseModel, Field


class Article(BaseModel):
    title: str = Field(..., description="The title of the article")
    summary: str = Field(..., description="A summary of the article")
    reference_links: List[str] = Field(
        ..., description="A list of reference links to the article"
    )


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
sync_hn_researcher = Agent(
    name="HackerNews Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

sync_article_reader = Agent(
    name="Article Reader",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Reads articles from URLs.",
    tools=[Newspaper4kTools()],
)

async_hn_researcher = Agent(
    name="HackerNews Researcher",
    model=OpenAIResponses(id="gpt-5.2-mini"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

async_web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIResponses(id="gpt-5.2-mini"),
    role="Searches the web for information on a topic",
    tools=[WebSearchTools()],
    add_datetime_to_context=True,
)

async_article_reader = Agent(
    name="Article Reader",
    role="Reads articles from URLs.",
    tools=[Newspaper4kTools()],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
sync_hn_team = Team(
    name="HackerNews Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[sync_hn_researcher, sync_article_reader],
    instructions=[
        "First, search hackernews for what the user is asking about.",
        "Then, ask the article reader to read the links for the stories to get more information.",
        "Important: you must provide the article reader with the links to read.",
        "Then, ask the web searcher to search for each story to get more information.",
        "Finally, provide a thoughtful and engaging summary.",
    ],
    output_schema=Article,
    add_member_tools_to_context=False,
    markdown=True,
    show_members_responses=True,
)

async_hn_team = Team(
    name="HackerNews Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[async_hn_researcher, async_web_searcher, async_article_reader],
    instructions=[
        "First, search hackernews for what the user is asking about.",
        "Then, ask the article reader to read the links for the stories to get more information.",
        "Important: you must provide the article reader with the links to read.",
        "Then, ask the web searcher to search for each story to get more information.",
        "Finally, provide a thoughtful and engaging summary.",
    ],
    output_schema=Article,
    add_member_tools_to_context=False,
    markdown=True,
    show_members_responses=True,
)


async def run_async_coordination() -> None:
    await async_hn_team.aprint_response(
        input="Write an article about the top 2 stories on hackernews"
    )


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    sync_hn_team.print_response(
        input="Write an article about the top 2 stories on hackernews", stream=True
    )

    # --- Async ---
    asyncio.run(run_async_coordination())
