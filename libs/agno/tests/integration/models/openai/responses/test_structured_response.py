import enum
from typing import Dict, List, Literal

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses
from agno.tools.websearch import WebSearchTools


class MovieScript(BaseModel):
    setting: str = Field(..., description="Provide a nice setting for a blockbuster movie.")
    ending: str = Field(
        ...,
        description="Ending of the movie. If not available, provide a happy ending.",
    )
    genre: str = Field(
        ...,
        description="Genre of the movie. If not available, select action, thriller or romantic comedy.",
    )
    name: str = Field(..., description="Give a name to this movie")
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(..., description="3 sentence storyline for the movie. Make it exciting!")
    rating: Dict[str, int] = Field(
        ...,
        description="Your own rating of the movie. 1-10. Return a dictionary with the keys 'story' and 'acting'.",
    )


def test_structured_response_with_integer_field():
    structured_output_agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        description="You help people write movie scripts.",
        output_schema=MovieScript,
    )
    response = structured_output_agent.run("New York")
    assert response.content is not None
    assert isinstance(response.content.rating, Dict)


def test_structured_response_with_enum_fields():
    class Grade(enum.Enum):
        A_PLUS = "a+"
        A = "a"
        B = "b"
        C = "c"
        D = "d"
        F = "f"

    class Recipe(BaseModel):
        recipe_name: str
        rating: Grade

    structured_output_agent = Agent(
        model=OpenAIResponses(id="gpt-4o"),
        description="You help generate recipe names and ratings.",
        output_schema=Recipe,
    )
    response = structured_output_agent.run("Generate a recipe name and rating.")
    assert response.content is not None
    assert isinstance(response.content.rating, Grade)
    assert isinstance(response.content.recipe_name, str)


class ResearchSummary(BaseModel):
    topic: str = Field(..., description="Main topic researched")
    key_findings: List[str] = Field(..., description="List of key findings from the research")
    summary: str = Field(..., description="Brief summary of the research")
    confidence_level: Literal["High", "Medium", "Low"] = Field(
        ..., description="High / Medium / Low confidence in the findings"
    )


def test_tool_use_with_structured_output():
    """Test basic tool use combined with structured output (non-streaming)."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-5-mini"),
        tools=[WebSearchTools()],
        output_schema=ResearchSummary,
        telemetry=False,
    )

    response = agent.run("Research the latest trends in machine learning on the internet and provide a summary")

    # Verify structured output format (this is what matters for the bug fix)
    assert response.content is not None
    assert isinstance(response.content, ResearchSummary)

    # Check fields are populated (don't care about specific content)
    assert isinstance(response.content.topic, str) and len(response.content.topic.strip()) > 0
    assert isinstance(response.content.key_findings, list) and len(response.content.key_findings) > 0
    assert isinstance(response.content.summary, str) and len(response.content.summary.strip()) > 0
    assert response.content.confidence_level in ["High", "Medium", "Low"]

    # Verify key findings have content
    for finding in response.content.key_findings:
        assert isinstance(finding, str) and len(finding.strip()) > 0

    # Verify tool usage occurred (this validates the bug fix)
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)


def test_tool_use_with_structured_output_stream():
    """Test streaming tool use combined with structured output - the main bug this PR fixes."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-5-mini"),
        tools=[WebSearchTools()],
        output_schema=ResearchSummary,
        telemetry=False,
    )

    response_stream = agent.run(
        "Research the latest trends in machine learning on the internet and provide a summary",
        stream=True,
        stream_events=True,
    )

    responses = []
    tool_call_seen = False
    final_content = None

    for event in response_stream:
        responses.append(event)

        # Check for tool call events
        if event.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(event, "tool") and event.tool:  # type: ignore
            if event.tool.tool_name:  # type: ignore
                tool_call_seen = True

        # Capture final structured content
        if hasattr(event, "content") and event.content is not None and isinstance(event.content, ResearchSummary):
            final_content = event.content

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"

    # Verify final structured output (the core of this bug fix test)
    assert final_content is not None
    assert isinstance(final_content, ResearchSummary)

    # Check structured fields are populated correctly
    assert isinstance(final_content.topic, str) and len(final_content.topic.strip()) > 0
    assert isinstance(final_content.key_findings, list) and len(final_content.key_findings) > 0
    assert isinstance(final_content.summary, str) and len(final_content.summary.strip()) > 0
    assert final_content.confidence_level in ["High", "Medium", "Low"]

    # Verify key findings have content
    for finding in final_content.key_findings:
        assert isinstance(finding, str) and len(finding.strip()) > 0


@pytest.mark.asyncio
async def test_async_tool_use_with_structured_output_stream():
    """Test async streaming tool use combined with structured output."""

    async def get_research_data(topic: str) -> str:
        """Get research data for a given topic."""
        return f"Research findings on {topic}: This topic has multiple aspects including technical implementations, best practices, current trends, and future prospects in the field."

    agent = Agent(
        model=OpenAIResponses(id="gpt-5-mini"),
        tools=[get_research_data],
        output_schema=ResearchSummary,
        telemetry=False,
    )

    responses = []
    tool_call_seen = False
    final_content = None

    async for event in agent.arun(
        "Research web development trends using available data", stream=True, stream_events=True
    ):
        responses.append(event)

        # Check for tool call events
        if event.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(event, "tool") and event.tool:  # type: ignore
            if event.tool.tool_name:  # type: ignore
                tool_call_seen = True

        # Capture final structured content
        if hasattr(event, "content") and event.content is not None and isinstance(event.content, ResearchSummary):
            final_content = event.content

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in async stream"

    # Verify final structured output (async version of the bug fix test)
    assert final_content is not None
    assert isinstance(final_content, ResearchSummary)

    # Check structured fields are populated correctly
    assert isinstance(final_content.topic, str) and len(final_content.topic.strip()) > 0
    assert isinstance(final_content.key_findings, list) and len(final_content.key_findings) > 0
    assert isinstance(final_content.summary, str) and len(final_content.summary.strip()) > 0
    assert final_content.confidence_level in ["High", "Medium", "Low"]

    # Verify key findings have content
    for finding in final_content.key_findings:
        assert isinstance(finding, str) and len(finding.strip()) > 0


def test_structured_response_strict_output_false():
    """Test structured response with strict_output=False (guided mode)"""
    guided_output_agent = Agent(
        model=OpenAIResponses(id="gpt-4o", strict_output=False),
        description="You write movie scripts.",
        output_schema=MovieScript,
    )
    response = guided_output_agent.run("Create a short action movie")
    assert response.content is not None
