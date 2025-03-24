from typing import List

from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools


def test_coordinator_team_basic():
    """Test basic functionality of a coordinator team."""
    researcher = Agent(
        name="Researcher",
        model=OpenAIChat("gpt-4o"),
        role="Research information",
        tools=[DuckDuckGoTools(cache_results=True)],
    )

    writer = Agent(name="Writer", model=OpenAIChat("gpt-4o"), role="Write content based on research")

    team = Team(
        name="Content Team",
        mode="coordinate",
        model=OpenAIChat("gpt-4o"),
        members=[researcher, writer],
        instructions=[
            "First, have the Researcher gather information on the topic.",
            "Then, have the Writer create content based on the research.",
        ],
    )

    response = team.run("Write a short article about climate change solutions")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert len(response.member_responses) == 2


def test_coordinator_team_with_context_sharing():
    """Test coordinator team with context sharing between members."""
    hn_researcher = Agent(
        name="HackerNews Researcher",
        model=OpenAIChat("gpt-4o"),
        role="Gets top stories from hackernews",
        tools=[HackerNewsTools()],
    )

    web_searcher = Agent(
        name="Web Searcher",
        model=OpenAIChat("gpt-4o"),
        role="Searches the web for additional information",
        tools=[DuckDuckGoTools(cache_results=True)],
    )

    team = Team(
        name="News Team",
        mode="coordinate",
        model=OpenAIChat("gpt-4o"),
        members=[hn_researcher, web_searcher],
        instructions=[
            "First, search hackernews for what the user is asking about.",
            "Then, ask the web searcher to search for each story to get more information.",
            "Finally, provide a thoughtful and engaging summary.",
        ],
        enable_agentic_context=True,
    )

    response = team.run("Summarize the top story on hackernews")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert len(response.member_responses) == 2


def test_coordinator_team_with_structured_output():
    """Test coordinator team with structured output."""

    class Article(BaseModel):
        title: str
        summary: str
        reference_links: List[str]

    hn_researcher = Agent(
        name="HackerNews Researcher",
        model=OpenAIChat("gpt-4o"),
        role="Gets top stories from hackernews",
        tools=[HackerNewsTools()],
    )

    web_searcher = Agent(
        name="Web Searcher",
        model=OpenAIChat("gpt-4o"),
        role="Searches the web for additional information",
        tools=[DuckDuckGoTools(cache_results=True)],
    )

    team = Team(
        name="News Team",
        mode="coordinate",
        model=OpenAIChat("gpt-4o"),
        members=[hn_researcher, web_searcher],
        instructions=[
            "First, search hackernews for what the user is asking about.",
            "Then, ask the web searcher to search for each story to get more information.",
            "Finally, provide a thoughtful and engaging summary.",
        ],
        response_model=Article,
    )

    response = team.run("Write an article about the top story on hackernews")

    assert response.content is not None
    assert isinstance(response.content, Article)
    assert response.content.title is not None
    assert response.content.summary is not None
    assert response.content.reference_links is not None
    assert len(response.content.reference_links) > 0


def test_coordinator_team_sequential_tasks():
    """Test coordinator team with sequential task execution."""
    data_collector = Agent(
        name="Data Collector",
        model=OpenAIChat("gpt-4o"),
        role="Collect data",
        tools=[DuckDuckGoTools(cache_results=True)],
    )

    data_analyzer = Agent(name="Data Analyzer", model=OpenAIChat("gpt-4o"), role="Analyze data")

    report_writer = Agent(name="Report Writer", model=OpenAIChat("gpt-4o"), role="Write reports based on analysis")

    team = Team(
        name="Research Team",
        mode="coordinate",
        model=OpenAIChat("gpt-4o"),
        members=[data_collector, data_analyzer, report_writer],
        instructions=[
            "First, have the Data Collector gather information.",
            "Then, have the Data Analyzer analyze the collected data.",
            "Finally, have the Report Writer create a comprehensive report.",
        ],
        enable_agentic_context=True,
    )

    response = team.run("Research the impact of AI on job markets")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert len(response.member_responses) == 3
