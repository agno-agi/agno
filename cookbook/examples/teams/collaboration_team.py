"""Example of a Team using the `collaborate` mode.

In Collaborate Mode, all team members are given the same task and the team leader synthesizes their outputs into a cohesive response.

Run `pip install agno arxiv pypdf pycountry` to install the dependencies.
"""

import asyncio
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.arxiv import ArxivTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools

arxiv_download_dir = Path(__file__).parent.joinpath("tmp", "arxiv_pdfs__{session_id}")
arxiv_download_dir.mkdir(parents=True, exist_ok=True)

reddit_researcher = Agent(
    name="Reddit Researcher",
    role="Research a topic on Reddit",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    add_name_to_context=True,
    instructions=dedent("""
    You are a Reddit researcher.
    You will be given a topic to research on Reddit.
    You will need to find the most relevant posts on Reddit.
    """),
)

hackernews_researcher = Agent(
    name="HackerNews Researcher",
    model=OpenAIChat("gpt-4o"),
    role="Research a topic on HackerNews.",
    tools=[HackerNewsTools()],
    add_name_to_context=True,
    instructions=dedent("""
    You are a HackerNews researcher.
    You will be given a topic to research on HackerNews.
    You will need to find the most relevant posts on HackerNews.
    """),
)

academic_paper_researcher = Agent(
    name="Academic Paper Researcher",
    model=OpenAIChat("gpt-4o"),
    role="Research academic papers and scholarly content",
    tools=[DuckDuckGoTools(), ArxivTools(download_dir=arxiv_download_dir)],
    add_name_to_context=True,
    instructions=dedent("""
    You are a academic paper researcher.
    You will be given a topic to research in academic literature.
    You will need to find relevant scholarly articles, papers, and academic discussions.
    Focus on peer-reviewed content and citations from reputable sources.
    Provide brief summaries of key findings and methodologies.
    """),
)

twitter_researcher = Agent(
    name="Twitter Researcher",
    model=OpenAIChat("gpt-4o"),
    role="Research trending discussions and real-time updates",
    tools=[DuckDuckGoTools()],
    add_name_to_context=True,
    instructions=dedent("""
    You are a Twitter/X researcher.
    You will be given a topic to research on Twitter/X.
    You will need to find trending discussions, influential voices, and real-time updates.
    Focus on verified accounts and credible sources when possible.
    Track relevant hashtags and ongoing conversations.
    """),
)


agent_team = Team(
    name="Discussion Team",
    model=OpenAIChat("gpt-4o"),
    members=[
        reddit_researcher,
        hackernews_researcher,
        academic_paper_researcher,
        twitter_researcher,
    ],
    delegate_to_all_members=True,
    instructions=[
        "You are a discussion master.",
        "You have to stop the discussion when you think the team has reached a consensus.",
    ],
    markdown=True,
    show_members_responses=True,
)

if __name__ == "__main__":
    asyncio.run(
        agent_team.aprint_response(
            input="Start the discussion on the topic: 'What is the best way to learn to code?'",
            stream=True,
        )
    )
