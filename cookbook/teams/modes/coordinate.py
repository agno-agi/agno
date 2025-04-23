"""
1. Run: `pip install openai duckduckgo-search newspaper4k lxml_html_clean agno` to install the dependencies
2. Run: `python cookbook/teams/coordinate/hackernews_team.py` to run the agent

This example demonstrates a coordinated team of AI agents working together to research topics across different platforms.

The team consists of three specialized agents:
1. HackerNews Researcher - Uses HackerNews API to find and analyze relevant HackerNews posts
2. Web Searcher - Uses DuckDuckGo to find and analyze relevant web pages
3. Article Reader - Reads articles from URLs

The team leader coordinates the agents by:
- Giving each agent a specific task
- Providing clear instructions for each agent
- Collecting and summarizing the results from each agent

"""

import asyncio
from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunResponse  # type: ignore
from agno.team import Team
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

article_reader = Agent(
    name="Article Reader",
    role="Reads articles from URLs.",
    tools=[Newspaper4kTools()],
)


hn_team = Team(
    name="HackerNews Team",
    mode="coordinate",
    model=OpenAIChat("gpt-4o"),
    members=[hn_researcher, web_searcher, article_reader],
    instructions=[
        "First, search hackernews for what the user is asking about.",
        "Then, ask the article reader to read the links for the stories to get more information.",
        "Important: you must provide the article reader with the links to read.",
        "Then, ask the web searcher to search for each story to get more information.",
        "Finally, provide a thoughtful and engaging summary.",
    ],
    response_model=Article,
    add_member_tools_to_system_message=False,
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
    enable_agentic_context=True,
)

if __name__ == "__main__":
    asyncio.run(
        hn_team.aprint_response(
            "Write an article about the top 2 stories on hackernews", stream=True
        )
    )
