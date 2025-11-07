import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team


class PersonSchema(BaseModel):
    name: str = Field(..., description="Person's name")
    age: int = Field(..., description="Person's age")


class BookSchema(BaseModel):
    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Book author")
    year: int = Field(..., description="Publication year")


def test_team_run_with_output_schema_override():
    """Test that output_schema can be overridden in team.run() and is restored after."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=PersonSchema,
        markdown=False,
    )

    assert team.output_schema == PersonSchema

    response = team.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert team.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_team_arun_with_output_schema_override():
    """Test that output_schema can be overridden in team.arun() and is restored after."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=PersonSchema,
        markdown=False,
    )

    assert team.output_schema == PersonSchema

    response = await team.arun(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert team.output_schema == PersonSchema


def test_team_run_without_default_schema_with_override():
    """Test output_schema override when team has no default schema."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        markdown=False,
    )

    assert team.output_schema is None

    response = team.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert team.output_schema is None


@pytest.mark.asyncio
async def test_team_arun_without_default_schema_with_override():
    """Test output_schema override in team.arun() when team has no default schema."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        markdown=False,
    )

    assert team.output_schema is None

    response = await team.arun(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert team.output_schema is None


def test_team_multiple_overrides_in_sequence():
    """Test multiple sequential calls with different schema overrides."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=PersonSchema,
        markdown=False,
    )

    response1 = team.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )
    assert isinstance(response1.content, BookSchema)
    assert team.output_schema == PersonSchema

    response2 = team.run(
        "Tell me about a person named John who is 30 years old",
        stream=False,
    )
    assert isinstance(response2.content, PersonSchema)
    assert team.output_schema == PersonSchema

    response3 = team.run(
        "Tell me about 'To Kill a Mockingbird' by Harper Lee published in 1960",
        output_schema=BookSchema,
        stream=False,
    )
    assert isinstance(response3.content, BookSchema)
    assert team.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_team_multiple_async_overrides_in_sequence():
    """Test multiple sequential async calls with different schema overrides."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=PersonSchema,
        markdown=False,
    )

    response1 = await team.arun(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )
    assert isinstance(response1.content, BookSchema)
    assert team.output_schema == PersonSchema

    response2 = await team.arun(
        "Tell me about a person named John who is 30 years old",
        stream=False,
    )
    assert isinstance(response2.content, PersonSchema)
    assert team.output_schema == PersonSchema

    response3 = await team.arun(
        "Tell me about 'To Kill a Mockingbird' by Harper Lee published in 1960",
        output_schema=BookSchema,
        stream=False,
    )
    assert isinstance(response3.content, BookSchema)
    assert team.output_schema == PersonSchema
