from typing import List

from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.hackernews import HackerNewsTools


def test_structured_output():
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
        model=OpenAIChat("gpt-4o-mini"),
        role="Gets top stories from hackernews.",
        tools=[HackerNewsTools()],
        response_model=HackerNewsArticle,
        structured_outputs=True,
    )

    hn_team = Agent(
        name="Hackernews Team",
        model=OpenAIChat("gpt-4o-mini"),
        team=[hn_researcher],
        instructions=[
            "First, search hackernews for what the user is asking about.",
            "Finally, provide a thoughtful and engaging summary.",
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
