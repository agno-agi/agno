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


def test_run_with_output_schema_override():
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


def test_run_streaming_with_output_schema_override():
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
async def test_arun_with_output_schema_override():
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
async def test_arun_streaming_with_output_schema_override():
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


def test_run_without_default_schema_with_override():
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
async def test_arun_without_default_schema_with_override():
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


def test_multiple_overrides_in_sequence():
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
async def test_multiple_async_overrides_in_sequence():
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
