import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput
from agno.models.openai import OpenAIChat


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


def test_run_with_output_schema():
    """Test that output_schema can be overridden in run() and is restored after."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    response: RunOutput = agent.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert agent.output_schema == PersonSchema


def test_run_streaming_with_output_schema():
    """Test that output_schema override works with streaming."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    final_response = None
    for event in agent.run(
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
    assert agent.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_arun_with_output_schema():
    """Test that output_schema can be overridden in arun() and is restored after."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    response: RunOutput = await agent.arun(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert agent.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_arun_streaming_with_output_schema():
    """Test that output_schema override works with async streaming."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    final_response = None
    async for event in agent.arun(
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
    assert agent.output_schema == PersonSchema


def test_run_without_default_schema():
    """Test output_schema override when agent has no default schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=False,
    )

    assert agent.output_schema is None

    response: RunOutput = agent.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert agent.output_schema is None


@pytest.mark.asyncio
async def test_arun_without_default_schema():
    """Test output_schema override in arun() when agent has no default schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=False,
    )

    assert agent.output_schema is None

    response: RunOutput = await agent.arun(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert agent.output_schema is None


def test_multiple_calls_in_sequence():
    """Test multiple sequential calls with different schema overrides."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    response1: RunOutput = agent.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )
    assert isinstance(response1.content, BookSchema)
    assert agent.output_schema == PersonSchema

    response2: RunOutput = agent.run(
        "Tell me about a person named John who is 30 years old",
        stream=False,
    )
    assert isinstance(response2.content, PersonSchema)
    assert agent.output_schema == PersonSchema

    response3: RunOutput = agent.run(
        "Tell me about 'To Kill a Mockingbird' by Harper Lee published in 1960",
        output_schema=BookSchema,
        stream=False,
    )
    assert isinstance(response3.content, BookSchema)
    assert agent.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_multiple_async_calls_in_sequence():
    """Test multiple sequential async calls with different schema overrides."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    response1: RunOutput = await agent.arun(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )
    assert isinstance(response1.content, BookSchema)
    assert agent.output_schema == PersonSchema

    response2: RunOutput = await agent.arun(
        "Tell me about a person named John who is 30 years old",
        stream=False,
    )
    assert isinstance(response2.content, PersonSchema)
    assert agent.output_schema == PersonSchema

    response3: RunOutput = await agent.arun(
        "Tell me about 'To Kill a Mockingbird' by Harper Lee published in 1960",
        output_schema=BookSchema,
        stream=False,
    )
    assert isinstance(response3.content, BookSchema)
    assert agent.output_schema == PersonSchema


def test_run_with_parser_model():
    """Test that output_schema override works with parser model."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    response: RunOutput = agent.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert agent.output_schema == PersonSchema


def test_run_streaming_with_parser_model():
    """Test that output_schema override works with parser model streaming."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    final_response = None
    for event in agent.run(
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
    assert agent.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_arun_with_parser_model():
    """Test that output_schema override works with parser model in arun()."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    response: RunOutput = await agent.arun(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert agent.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_arun_streaming_with_parser_model():
    """Test that output_schema override works with parser model async streaming."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    final_response = None
    async for event in agent.arun(
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
    assert agent.output_schema == PersonSchema


def test_run_with_structured_outputs():
    """Test that output_schema override works with structured outputs."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        structured_outputs=True,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    response: RunOutput = agent.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert agent.output_schema == PersonSchema


def test_run_with_json_mode():
    """Test that output_schema override works with JSON mode."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        use_json_mode=True,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    response: RunOutput = agent.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert agent.output_schema == PersonSchema


def test_run_with_default():
    """Test that passing output_schema=None uses the default schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    response: RunOutput = agent.run(
        "Tell me about a person named John who is 30 years old",
        output_schema=None,
        stream=False,
    )

    assert isinstance(response.content, PersonSchema)
    assert response.content.name is not None
    assert response.content.age is not None
    assert agent.output_schema == PersonSchema


def test_run_streaming_without_default_schema():
    """Test streaming run without default schema, with override."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=False,
    )

    assert agent.output_schema is None

    final_response = None
    for event in agent.run(
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
    assert agent.output_schema is None


@pytest.mark.asyncio
async def test_arun_streaming_without_default_schema():
    """Test async streaming run without default schema, with override."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=False,
    )

    assert agent.output_schema is None

    final_response = None
    async for event in agent.arun(
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
    assert agent.output_schema is None


def test_run_streaming_with_json_mode():
    """Test streaming run with JSON mode and override."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        use_json_mode=True,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    final_response = None
    for event in agent.run(
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
    assert agent.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_arun_with_json_mode():
    """Test async run with JSON mode and override."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        use_json_mode=True,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    response = await agent.arun(
        "Tell me about 'The Grapes of Wrath' by John Steinbeck published in 1939",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert agent.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_arun_streaming_with_json_mode():
    """Test async streaming run with JSON mode and override."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        use_json_mode=True,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    final_response = None
    async for event in agent.arun(
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
    assert agent.output_schema == PersonSchema


def test_run_streaming_with_structured_outputs():
    """Test streaming run with structured outputs and override."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        structured_outputs=True,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    final_response = None
    for event in agent.run(
        "Tell me about 'A Tale of Two Cities' by Charles Dickens published in 1859",
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
    assert agent.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_arun_with_structured_outputs():
    """Test async run with structured outputs and override."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        structured_outputs=True,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    response = await agent.arun(
        "Tell me about 'Jane Eyre' by Charlotte Bronte published in 1847",
        output_schema=BookSchema,
        stream=False,
    )

    assert isinstance(response.content, BookSchema)
    assert response.content.title is not None
    assert response.content.author is not None
    assert response.content.year is not None
    assert agent.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_arun_streaming_with_structured_outputs():
    """Test async streaming run with structured outputs and override."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        structured_outputs=True,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    final_response = None
    async for event in agent.arun(
        "Tell me about 'Wuthering Heights' by Emily Bronte published in 1847",
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
    assert agent.output_schema == PersonSchema


@pytest.mark.asyncio
async def test_arun_with_default():
    """Test that passing output_schema=None uses default schema in async."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=PersonSchema,
        markdown=False,
    )

    assert agent.output_schema == PersonSchema

    response = await agent.arun(
        "Tell me about a person named Carol who is 28 years old",
        output_schema=None,
        stream=False,
    )

    assert isinstance(response.content, PersonSchema)
    assert response.content.name is not None
    assert response.content.age is not None
    assert agent.output_schema == PersonSchema


def test_run_with_json_schema():
    """Test that JSON schema works as output_schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=person_json_schema,
        markdown=False,
    )

    response: RunOutput = agent.run(
        "Tell me about Albert Einstein who was 76 years old",
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert response.content_type == "dict"


@pytest.mark.asyncio
async def test_arun_with_json_schema():
    """Test that JSON schema works with async run."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=person_json_schema,
        markdown=False,
    )

    response: RunOutput = await agent.arun(
        "Tell me about Isaac Newton who was 84 years old",
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert response.content_type == "dict"


def test_run_with_json_schema_override():
    """Test that JSON schema can be overridden at runtime."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=person_json_schema,
        markdown=False,
    )

    assert agent.output_schema == person_json_schema

    response: RunOutput = agent.run(
        "Tell me about '1984' by George Orwell published in 1949",
        output_schema=book_json_schema,
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "title" in response.content
    assert "author" in response.content
    assert "year" in response.content
    assert agent.output_schema == person_json_schema


@pytest.mark.asyncio
async def test_arun_with_json_schema_override():
    """Test that JSON schema override works with async."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=person_json_schema,
        markdown=False,
    )

    response: RunOutput = await agent.arun(
        "Tell me about 'The Great Gatsby' by F. Scott Fitzgerald published in 1925",
        output_schema=book_json_schema,
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "title" in response.content
    assert "author" in response.content
    assert "year" in response.content
    assert agent.output_schema == person_json_schema


def test_run_streaming_with_json_schema():
    """Test that JSON schema works with streaming."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=person_json_schema,
        markdown=False,
    )

    final_response = None
    for event in agent.run(
        "Tell me about Marie Curie who was 66 years old",
        stream=True,
    ):
        if hasattr(event, "content"):
            final_response = event

    assert final_response is not None
    assert isinstance(final_response.content, dict)
    assert "name" in final_response.content
    assert "age" in final_response.content


@pytest.mark.asyncio
async def test_arun_streaming_with_json_schema():
    """Test that JSON schema works with async streaming."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=person_json_schema,
        markdown=False,
    )

    final_response = None
    async for event in agent.arun(
        "Tell me about Nikola Tesla who was 86 years old",
        stream=True,
    ):
        if hasattr(event, "content"):
            final_response = event

    assert final_response is not None
    assert isinstance(final_response.content, dict)
    assert "name" in final_response.content
    assert "age" in final_response.content


def test_run_json_schema_with_structured_outputs():
    """Test JSON schema with structured_outputs=True."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=person_json_schema,
        structured_outputs=True,
        markdown=False,
    )

    response: RunOutput = agent.run(
        "Tell me about Charles Darwin who was 73 years old",
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert response.content_type == "dict"


@pytest.mark.asyncio
async def test_arun_json_schema_with_structured_outputs():
    """Test JSON schema with structured_outputs=True in async."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=person_json_schema,
        structured_outputs=True,
        markdown=False,
    )

    response: RunOutput = await agent.arun(
        "Tell me about Galileo Galilei who was 77 years old",
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert response.content_type == "dict"


def test_run_json_schema_without_default():
    """Test JSON schema override when agent has no default schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=False,
    )

    assert agent.output_schema is None

    response: RunOutput = agent.run(
        "Tell me about Ada Lovelace who was 36 years old",
        output_schema=person_json_schema,
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert agent.output_schema is None


@pytest.mark.asyncio
async def test_arun_json_schema_without_default():
    """Test JSON schema override in async when agent has no default schema."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=False,
    )

    assert agent.output_schema is None

    response: RunOutput = await agent.arun(
        "Tell me about Alan Turing who was 41 years old",
        output_schema=person_json_schema,
        stream=False,
    )

    assert isinstance(response.content, dict)
    assert "name" in response.content
    assert "age" in response.content
    assert agent.output_schema is None
