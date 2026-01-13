from typing import List

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat


class ParkGuide(BaseModel):
    park_name: str = Field(..., description="The official name of the national park.")
    activities: List[str] = Field(
        ..., description="A list of popular activities to do in the park. Provide at least three."
    )
    best_season_to_visit: str = Field(
        ..., description="The best season to visit the park (e.g., Spring, Summer, Autumn, Winter)."
    )


def test_claude_with_openai_parser_model():
    park_agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514"),  # Main model to generate the content
        description="You are an expert on national parks and provide concise guides.",
        output_schema=ParkGuide,
        parser_model=OpenAIChat(id="gpt-4o"),  # Model to parse the output
    )

    response = park_agent.run("Tell me about Yosemite National Park.")

    assert response.content is not None
    assert isinstance(response.content, ParkGuide)
    assert isinstance(response.content.park_name, str)
    assert len(response.content.park_name) > 0

    assert isinstance(response.content.activities, list)
    assert len(response.content.activities) >= 2
    for activity in response.content.activities:
        assert isinstance(activity, str)
        assert len(activity) > 0

    assert isinstance(response.content.best_season_to_visit, str)
    assert len(response.content.best_season_to_visit) > 0


def test_openai_with_claude_parser_model():
    park_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),  # Main model to generate the content
        description="You are an expert on national parks and provide concise guides.",
        output_schema=ParkGuide,
        parser_model=Claude(id="claude-sonnet-4-20250514"),  # Model to parse the output
    )

    response = park_agent.run("Tell me about Yosemite National Park.")

    assert response.content is not None
    assert isinstance(response.content, ParkGuide)
    assert isinstance(response.content.park_name, str)
    assert len(response.content.park_name) > 0

    assert isinstance(response.content.activities, list)
    assert len(response.content.activities) >= 2
    for activity in response.content.activities:
        assert isinstance(activity, str)
        assert len(activity) > 0

    assert isinstance(response.content.best_season_to_visit, str)
    assert len(response.content.best_season_to_visit) > 0


def test_gemini_with_openai_parser_model():
    park_agent = Agent(
        model=Gemini(id="gemini-2.0-flash-001"),  # Main model to generate the content
        description="You are an expert on national parks and provide concise guides.",
        output_schema=ParkGuide,
        parser_model=OpenAIChat(id="gpt-4o"),  # Model to parse the output
    )

    response = park_agent.run("Tell me about Yosemite National Park.")

    assert response.content is not None
    assert isinstance(response.content, ParkGuide)
    assert isinstance(response.content.park_name, str)
    assert len(response.content.park_name) > 0

    assert isinstance(response.content.activities, list)
    assert len(response.content.activities) >= 2
    for activity in response.content.activities:
        assert isinstance(activity, str)
        assert len(activity) > 0

    assert isinstance(response.content.best_season_to_visit, str)
    assert len(response.content.best_season_to_visit) > 0


def test_parser_model_stream(shared_db):
    park_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),  # Main model to generate the content
        description="You are an expert on national parks and provide concise guides.",
        output_schema=ParkGuide,
        db=shared_db,
        parser_model=Claude(id="claude-sonnet-4-20250514"),  # Model to parse the output
    )

    response = park_agent.run("Tell me about Yosemite National Park.", stream=True)

    for event in response:
        pass

    run_response = park_agent.get_last_run_output()

    assert run_response.content is not None
    assert isinstance(run_response.content.get("park_name"), str)
    assert len(run_response.content.get("park_name")) > 0

    assert isinstance(run_response.content.get("activities"), list)
    assert len(run_response.content.get("activities")) >= 2
    for activity in run_response.content.get("activities"):
        assert isinstance(activity, str)
        assert len(activity) > 0
