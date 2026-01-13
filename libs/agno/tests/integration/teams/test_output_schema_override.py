import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team


@pytest.fixture(autouse=True)
def reset_async_client():
    """Reset global async HTTP client between tests to avoid event loop conflicts."""
    import agno.utils.http as http_utils

    # Reset before test
    http_utils._global_async_client = None
    yield
    # Reset after test
    http_utils._global_async_client = None


class PersonSchema(BaseModel):
    name: str = Field(..., description="Person's name")
    age: int = Field(..., description="Person's age")


class BookSchema(BaseModel):
    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Book author")
    year: int = Field(..., description="Publication year")


person_json_schema = {
    "type": "json_schema",
    "json_schema": {
        "name": "PersonInfo",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Person's full name"},
                "age": {"type": "integer", "description": "Person's age"},
            },
            "required": ["name", "age"],
            "additionalProperties": False,
        },
    },
}

book_json_schema = {
    "type": "json_schema",
    "json_schema": {
        "name": "BookInfo",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Book title"},
                "author": {"type": "string", "description": "Author name"},
                "year": {"type": "integer", "description": "Publication year"},
            },
            "required": ["title", "author", "year"],
            "additionalProperties": False,
        },
    },
}


def test_team_run_with_output_schema():
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
async def test_team_arun_with_output_schema():
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


def test_team_run_without_default_schema():
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
async def test_team_arun_without_default_schema():
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


def test_team_multiple_calls_in_sequence():
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
async def test_team_multiple_async_calls_in_sequence():
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


def test_team_run_streaming_with_output_schema():
    """Test that output_schema override works with team streaming."""
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

    final_response = None
    for event in team.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=True,
    ):
        if hasattr(event, "content"):
            final_response = event

    assert final_response is not None
    assert isinstance(final_response.content, BookSchema)
    assert final_response.content.title is not None
    assert final_response.content.author is not None
    assert final_response.content.year is not None
    assert team.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_team_arun_streaming_with_output_schema():
    """Test that output_schema override works with team async streaming."""
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

    final_response = None
    async for event in team.arun(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=True,
    ):
        if hasattr(event, "content"):
            final_response = event

    assert final_response is not None
    assert isinstance(final_response.content, BookSchema)
    assert final_response.content.title is not None
    assert final_response.content.author is not None
    assert final_response.content.year is not None
    assert team.output_schema == PersonSchema


def test_team_run_with_parser_model():
    """Test that output_schema override works with team parser model."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        parser_model=OpenAIChat(id="gpt-4o-mini"),
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


def test_team_run_streaming_with_parser_model():
    """Test that output_schema override works with team parser model streaming."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert team.output_schema == PersonSchema

    final_response = None
    for event in team.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=True,
    ):
        if hasattr(event, "content"):
            final_response = event

    assert final_response is not None
    assert isinstance(final_response.content, BookSchema)
    assert final_response.content.title is not None
    assert final_response.content.author is not None
    assert final_response.content.year is not None
    assert team.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_team_arun_with_parser_model():
    """Test that output_schema override works with team parser model in arun()."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        parser_model=OpenAIChat(id="gpt-4o-mini"),
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


@pytest.mark.asyncio
async def test_team_arun_streaming_with_parser_model():
    """Test that output_schema override works with team parser model async streaming."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert team.output_schema == PersonSchema

    final_response = None
    async for event in team.arun(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=True,
    ):
        if hasattr(event, "content"):
            final_response = event

    assert final_response is not None
    assert isinstance(final_response.content, BookSchema)
    assert final_response.content.title is not None
    assert final_response.content.author is not None
    assert final_response.content.year is not None
    assert team.output_schema == PersonSchema


def test_team_run_with_json_mode():
    """Test that output_schema override works with team JSON mode."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=PersonSchema,
        use_json_mode=True,
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


def test_team_run_with_default():
    """Test that passing output_schema=None uses the default schema for team."""
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
        "Tell me about a person named John who is 30 years old",
        output_schema=None,
        stream=False,
    )

    assert isinstance(response.content, PersonSchema)
    assert response.content.name is not None
    assert response.content.age is not None
    assert team.output_schema == PersonSchema


def test_team_run_streaming_without_default_schema():
    """Test team streaming run without default schema, with override."""
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

    final_response = None
    for event in team.run(
        "Tell me about 'The Catcher in the Rye' by J.D. Salinger published in 1951",
        output_schema=BookSchema,
        stream=True,
    ):
        if hasattr(event, "content"):
            final_response = event

    assert final_response is not None
    assert isinstance(final_response.content, BookSchema)
    assert final_response.content.title is not None
    assert final_response.content.author is not None
    assert final_response.content.year is not None
    assert team.output_schema is None


@pytest.mark.asyncio
async def test_team_arun_streaming_without_default_schema():
    """Test team async streaming run without default schema, with override."""
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

    final_response = None
    async for event in team.arun(
        "Tell me about 'War and Peace' by Leo Tolstoy published in 1869",
        output_schema=BookSchema,
        stream=True,
    ):
        if hasattr(event, "content"):
            final_response = event

    assert final_response is not None
    assert isinstance(final_response.content, BookSchema)
    assert final_response.content.title is not None
    assert final_response.content.author is not None
    assert final_response.content.year is not None
    assert team.output_schema is None


def test_team_run_streaming_with_json_mode():
    """Test team streaming run with JSON mode and override."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=PersonSchema,
        use_json_mode=True,
        markdown=False,
    )

    assert team.output_schema == PersonSchema

    final_response = None
    for event in team.run(
        "Tell me about 'Slaughterhouse-Five' by Kurt Vonnegut published in 1969",
        output_schema=BookSchema,
        stream=True,
    ):
        if hasattr(event, "content"):
            final_response = event

    assert final_response is not None
    assert isinstance(final_response.content, BookSchema)
    assert final_response.content.title is not None
    assert final_response.content.author is not None
    assert final_response.content.year is not None
    assert team.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_team_arun_with_json_mode():
    """Test team async run with JSON mode and override."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=PersonSchema,
        use_json_mode=True,
        markdown=False,
    )

    assert team.output_schema == PersonSchema

    response = await team.arun(
        "Tell me about 'The Grapes of Wrath' by John Steinbeck published in 1939",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert team.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_team_arun_streaming_with_json_mode():
    """Test team async streaming run with JSON mode and override."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=PersonSchema,
        use_json_mode=True,
        markdown=False,
    )

    assert team.output_schema == PersonSchema

    final_response = None
    async for event in team.arun(
        "Tell me about 'Of Mice and Men' by John Steinbeck published in 1937",
        output_schema=BookSchema,
        stream=True,
    ):
        if hasattr(event, "content"):
            final_response = event

    assert final_response is not None
    assert isinstance(final_response.content, BookSchema)
    assert final_response.content.title is not None
    assert final_response.content.author is not None
    assert final_response.content.year is not None
    assert team.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_team_arun_with_default():
    """Test that passing output_schema=None uses default schema for team in async."""
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
        "Tell me about a person named Carol who is 28 years old",
        output_schema=None,
        stream=False,
    )

    assert isinstance(response.content, PersonSchema)
    assert response.content.name is not None
    assert response.content.age is not None
    assert team.output_schema == PersonSchema


def test_team_run_with_json_schema():
    """Test that JSON schema works as team output_schema."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=person_json_schema,
        markdown=False,
    )

    response = team.run(
        "Tell me about Albert Einstein who was 76 years old",
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert response.content_type == "dict"


@pytest.mark.asyncio
async def test_team_arun_with_json_schema():
    """Test that JSON schema works with team async run."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=person_json_schema,
        markdown=False,
    )

    response = await team.arun(
        "Tell me about Isaac Newton who was 84 years old",
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert response.content_type == "dict"


def test_team_run_with_json_schema_override():
    """Test that JSON schema can be overridden at runtime in team."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=person_json_schema,
        markdown=False,
    )

    assert team.output_schema == person_json_schema

    response = team.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=book_json_schema,
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "title" in response.content
    assert "author" in response.content
    assert "year" in response.content
    assert team.output_schema == person_json_schema


@pytest.mark.asyncio
async def test_team_arun_with_json_schema_override():
    """Test that JSON schema override works with team async."""
    agent1 = Agent(
        name="Agent1",
        role="Information provider",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        output_schema=person_json_schema,
        markdown=False,
    )

    response = await team.arun(
        "Tell me about 'The Great Gatsby' by F. Scott Fitzgerald published in 1925",
        output_schema=book_json_schema,
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "title" in response.content
    assert "author" in response.content
    assert "year" in response.content
    assert team.output_schema == person_json_schema


def test_team_run_json_schema_without_default():
    """Test JSON schema override when team has no default schema."""
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
        "Tell me about Ada Lovelace who was 36 years old",
        output_schema=person_json_schema,
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert team.output_schema is None


@pytest.mark.asyncio
async def test_team_arun_json_schema_without_default():
    """Test JSON schema override in async when team has no default schema."""
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
        "Tell me about Alan Turing who was 41 years old",
        output_schema=person_json_schema,
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert team.output_schema is None
