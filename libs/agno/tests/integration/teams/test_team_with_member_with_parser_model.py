from typing import List

from pydantic import BaseModel, Field

from agno.agent import Agent
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


def test_team_with_parser_model():
    agent = Agent(
        name="National Park Expert",
        model=OpenAIChat(id="gpt-4o"),
        output_schema=ParkGuide,
        parser_model=OpenAIChat(id="gpt-4o-mini"),  # Use OpenAI instead of Claude
        description="You are an expert on national parks and provide concise guides.",
    )

    team = Team(
        name="National Park Expert",
        members=[agent],
        respond_directly=True,
        telemetry=False,
    )

    response = team.run("Tell me about Yosemite National Park.")
    print(response.content)

    assert response.content is not None
    assert isinstance(response.content, ParkGuide)
    assert isinstance(response.content.park_name, str)
    assert len(response.content.park_name) > 0


def test_team_with_parser_model_stream(shared_db):
    agent = Agent(
        name="National Park Expert",
        model=OpenAIChat(id="gpt-4o"),
        output_schema=ParkGuide,
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        description="You are an expert on national parks and provide concise guides.",
    )

    team = Team(
        name="National Park Expert",
        members=[agent],
        db=shared_db,
        respond_directly=True,
        telemetry=False,
    )

    response = team.run("Tell me about Yosemite National Park.", stream=True)
    final_content = None

    for event in response:
        # Capture content from events during streaming
        if hasattr(event, "content") and isinstance(event.content, ParkGuide):
            final_content = event.content

    # Fallback: try to get from database if events didn't capture it
    if final_content is None:
        run_response = team.get_last_run_output()
        if run_response and run_response.content:
            final_content = run_response.content

    assert final_content is not None
    assert isinstance(final_content, ParkGuide)
    assert isinstance(final_content.park_name, str)
    assert len(final_content.park_name) > 0
