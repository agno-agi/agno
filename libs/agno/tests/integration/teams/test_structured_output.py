from typing import List

import pytest
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.hackernews import HackerNewsTools


@pytest.mark.skip("Test is flaky with current team implementation")
def test_structured_output():
    class Article(BaseModel):
        title: str
        summary: str
        reference_links: List[str]

    class HackerNewsArticle(BaseModel):
        title: str
        summary: str

    hn_researcher = Agent(
        name="HackerNews Researcher",
        model=OpenAIChat("gpt-4o"),
        role="Gets top stories from hackernews.",
        instructions="Only return valid JSON",
        tools=[HackerNewsTools()],
        response_model=HackerNewsArticle,
        structured_outputs=True,
    )

    hn_team = Agent(
        name="Hackernews Team",
        model=OpenAIChat("gpt-4o"),
        team=[hn_researcher],
        instructions=[
            "First, search hackernews for what the user is asking about.",
            "Finally, provide a thoughtful and engaging summary.",
            "Only return valid JSON",
        ],
        response_model=Article,
        structured_outputs=True,
        show_tool_calls=True,
        markdown=True,
    )

    response = hn_team.run("Write an article about the top 2 stories on hackernews", stream=True)

    assert isinstance(response.content, Article)
    assert response.content.title is not None
    assert response.content.summary is not None


def test_response_model():
    class Article(BaseModel):
        title: str
        summary: str
        reference_links: List[str]

    class HackerNewsArticle(BaseModel):
        title: str
        summary: str
        reference_links: List[str]

    hn_researcher = Agent(
        name="HackerNews Researcher",
        model=OpenAIChat("gpt-4o"),
        role="Gets top stories from hackernews.",
        tools=[HackerNewsTools()],
        response_model=HackerNewsArticle,
    )

    hn_team = Agent(
        name="Hackernews Team",
        model=OpenAIChat("gpt-4o"),
        team=[hn_researcher],
        instructions=[
            "First, search hackernews for what the user is asking about.",
            "Finally, provide a thoughtful and engaging summary.",
        ],
        response_model=Article,
        show_tool_calls=True,
        markdown=True,
    )

    response = hn_team.run("Write an article about the top 2 stories on hackernews", stream=True)

    assert isinstance(response.content, Article)
    assert response.content.title is not None
    assert response.content.summary is not None
