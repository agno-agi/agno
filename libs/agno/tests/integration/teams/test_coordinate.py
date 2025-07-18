from typing import List

from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team


def test_coordinator_team_basic():
    """Test basic functionality of a coordinator team."""

    def get_climate_change_info() -> str:
        return "Climate change is a global issue that requires urgent action."

    researcher = Agent(
        name="Researcher",
        model=OpenAIChat("gpt-4o"),
        role="Research information",
        tools=[get_climate_change_info],
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

    def get_hackernews_info() -> str:
        return "The top story on hackernews is about climate change."

    def get_web_info() -> str:
        return "The web is full of information about climate change."

    hn_researcher = Agent(
        name="HackerNews Researcher",
        model=OpenAIChat("gpt-4o"),
        role="Gets top stories from hackernews",
        tools=[get_hackernews_info],
    )

    web_searcher = Agent(
        name="Web Searcher",
        model=OpenAIChat("gpt-4o"),
        role="Searches the web for additional information",
        tools=[get_web_info],
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

    def get_hackernews_info() -> str:
        return "The top story on hackernews is about climate change."

    def get_web_info() -> str:
        return "The web is full of information about climate change."

    hn_researcher = Agent(
        name="HackerNews Researcher",
        model=OpenAIChat("gpt-4o-mini"),
        role="Gets top stories from hackernews",
        tools=[get_hackernews_info],
    )

    web_searcher = Agent(
        name="Web Searcher",
        model=OpenAIChat("gpt-4o-mini"),
        role="Searches the web for additional information",
        tools=[get_web_info],
    )

    team = Team(
        name="News Team",
        mode="coordinate",
        model=OpenAIChat("gpt-4o-mini"),
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
