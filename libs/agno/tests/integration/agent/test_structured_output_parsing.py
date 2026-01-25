from typing import List

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai.chat import OpenAIChat  # noqa


def test_structured_output_parsing_with_quotes():
    class MovieScript(BaseModel):
        script: str = Field(..., description="The script of the movie.")
        name: str = Field(..., description="Give a name to this movie")
        characters: List[str] = Field(..., description="Name of characters for this movie.")

    movie_agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        description="You help people write movie scripts. Always add some example dialog in your scripts in double quotes.",
        output_schema=MovieScript,
    )

    # Get the response in a variable
    response: RunOutput = movie_agent.run("New York")

    # Assert the response is a MovieScript instance
    assert isinstance(response.content, MovieScript)

    # Assert the MovieScript response contains all expected fields
    assert response.content.script is not None
    assert response.content.name is not None
    assert response.content.characters is not None


def test_run_json_schema_output():
    """Test that JSON schema works as output_schema."""

    movie_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "MovieScript",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Give a name to this movie"},
                    "genre": {"type": "string", "description": "Movie genre"},
                    "characters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Name of characters for this movie",
                    },
                },
                "required": ["name", "genre", "characters"],
                "additionalProperties": False,
            },
        },
    }

    movie_agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        description="You help people write movie scripts.",
        output_schema=movie_schema,
    )

    response: RunOutput = movie_agent.run("Create a sci-fi movie set in 2150")

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "genre" in response.content
    assert "characters" in response.content
    assert isinstance(response.content["characters"], list)
    assert response.content_type == "dict"


@pytest.mark.asyncio
async def test_arun_json_schema_output():
    """Test that JSON schema works with async run."""

    movie_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "MovieScript",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Give a name to this movie"},
                    "genre": {"type": "string", "description": "Movie genre"},
                    "characters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Name of characters for this movie",
                    },
                },
                "required": ["name", "genre", "characters"],
                "additionalProperties": False,
            },
        },
    }

    movie_agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        description="You help people write movie scripts.",
        output_schema=movie_schema,
    )

    response: RunOutput = await movie_agent.arun("Create a fantasy movie with magic")

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "genre" in response.content
    assert "characters" in response.content
    assert isinstance(response.content["characters"], list)
    assert response.content_type == "dict"


def test_run_json_schema_with_structured_outputs():
    """Test JSON schema with structured_outputs=True."""

    person_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "PersonInfo",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Person's full name"},
                    "age": {"type": "integer", "description": "Person's age"},
                    "occupation": {"type": "string", "description": "Person's job"},
                },
                "required": ["name", "age", "occupation"],
                "additionalProperties": False,
            },
        },
    }

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=person_schema,
        structured_outputs=True,
    )

    response: RunOutput = agent.run("Tell me about Albert Einstein")

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert "occupation" in response.content
    assert response.content_type == "dict"


@pytest.mark.asyncio
async def test_arun_json_schema_with_structured_outputs():
    """Test JSON schema with structured_outputs=True in async."""

    person_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "PersonInfo",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Person's full name"},
                    "age": {"type": "integer", "description": "Person's age"},
                    "occupation": {"type": "string", "description": "Person's job"},
                },
                "required": ["name", "age", "occupation"],
                "additionalProperties": False,
            },
        },
    }

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=person_schema,
        structured_outputs=True,
    )

    response: RunOutput = await agent.arun("Tell me about Marie Curie")

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert "occupation" in response.content
    assert response.content_type == "dict"
