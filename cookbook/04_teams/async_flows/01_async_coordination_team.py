"""
1. Run: `pip install openai ddgs newspaper4k lxml_html_clean agno` to install the dependencies
2. Run: `python cookbook/teams/async/modes/02_async_coordinate.py` to run the agent

This example demonstrates a coordinated team of AI agents working together asynchronously to research topics across different platforms.

The team consists of two specialized agents:
1. HackerNews Researcher - Uses HackerNews API to find and analyze relevant HackerNews posts
2. Article Reader - Reads articles from URLs

"""

import asyncio
from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.newspaper4k import Newspaper4kTools
from pydantic import BaseModel, Field


class Article(BaseModel):
    title: str = Field(..., description="The title of the article")
    summary: str = Field(..., description="A summary of the article")
    reference_links: List[str] = Field(
        ..., description="A list of reference links to the article"
    )


hn_researcher = Agent(
    name="HackerNews Researcher",
    model=OpenAIChat("o3-mini"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIChat("o3-mini"),
    role="Searches the web for information on a topic",
    tools=[DuckDuckGoTools()],
    add_datetime_to_context=True,
)

article_reader = Agent(
    name="Article Reader",
    role="Reads articles from URLs.",
    tools=[Newspaper4kTools()],
)


hn_team = Team(
    name="HackerNews Team",
    model=OpenAIChat("o3"),
    members=[hn_researcher, web_searcher, article_reader],
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


async def main():
    """Main async function demonstrating coordinated team mode."""
    await hn_team.aprint_response(
        input="Write an article about the top 2 stories on hackernews"
    )


if __name__ == "__main__":
    asyncio.run(main())
