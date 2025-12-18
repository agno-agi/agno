"""
1. Run: `pip install openai ddgs newspaper4k lxml_html_clean agno` to install the dependencies
2. Run: `python cookbook/teams/async/modes/02_async_coordinate.py` to run the agent

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

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
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
    model=OpenAIChat("gpt-5-mini"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

article_reader = Agent(
    name="Article Reader",
    model=OpenAIChat("gpt-5-mini"),
    role="Reads articles from URLs.",
    tools=[Newspaper4kTools()],
)


hn_team = Team(
    name="HackerNews Team",
    model=OpenAIChat("gpt-5-mini"),
    members=[hn_researcher, article_reader],
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


hn_team.print_response(
    input="Write an article about the top 2 stories on hackernews", stream=True
)
