from typing import List

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team import Team


class ParkGuide(BaseModel):
    park_name: str = Field(..., description="The official name of the national park.")
    activities: List[str] = Field(
        ..., description="A list of popular activities to do in the park. Provide at least three."
    )
    best_season_to_visit: str = Field(
        ..., description="The best season to visit the park (e.g., Spring, Summer, Autumn, Winter)."
    )


agent = Agent(
    name="National Park Expert",
    model=OpenAIChat(id="gpt-4o"),
    response_model=ParkGuide,
    parser_model=Claude(id="claude-sonnet-4-20250514"),
    description="You are an expert on national parks and provide concise guides.",
)

team = Team(
    name="National Park Expert",
    mode="route",
    members=[agent],
    telemetry=False,
    monitoring=False,
)


def test_team_with_parser_model():
    response = team.run("Tell me about Yosemite National Park.")
    print(response.content)

    assert response.content is not None
    assert isinstance(response.content, ParkGuide)
    assert isinstance(response.content.park_name, str)
    assert len(response.content.park_name) > 0


def test_team_with_parser_model_stream():
    response = team.run("Tell me about Yosemite National Park.", stream=True)
    for event in response:
        print(event.event)

    assert team.run_response.content is not None
    assert isinstance(team.run_response.content, ParkGuide)
    assert isinstance(team.run_response.content.park_name, str)
    assert len(team.run_response.content.park_name) > 0
