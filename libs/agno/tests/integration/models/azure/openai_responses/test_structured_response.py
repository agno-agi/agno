"""
Integration tests for Azure OpenAI Responses API streaming with structured responses.

These tests require the following environment variables:
    AZURE_OPENAI_API_KEY: Your Azure OpenAI API key
    AZURE_OPENAI_ENDPOINT: Your Azure OpenAI endpoint
"""

from typing import List, Literal

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.azure import AzureOpenAIResponses


def search_web(query: str) -> str:
    """Search the web for information."""
    return f"Search results for '{query}': Machine learning trends include transformers, LLMs, multimodal models, and edge AI deployment."


class ResearchSummary(BaseModel):
    topic: str = Field(..., description="Main topic researched")
    key_findings: List[str] = Field(..., description="List of key findings from the research")
    summary: str = Field(..., description="Brief summary of the research")
    confidence_level: Literal["High", "Medium", "Low"] = Field(
        ..., description="High / Medium / Low confidence in the findings"
    )


def test_tool_use_with_structured_output_stream():
    """Test streaming tool use combined with structured output."""
    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
        tools=[search_web],
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

        if event.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(event, "tool") and event.tool:  # type: ignore
            if event.tool.tool_name:  # type: ignore
                tool_call_seen = True

        if hasattr(event, "content") and event.content is not None and isinstance(event.content, ResearchSummary):
            final_content = event.content

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"

    assert final_content is not None
    assert isinstance(final_content, ResearchSummary)

    assert isinstance(final_content.topic, str) and len(final_content.topic.strip()) > 0
    assert isinstance(final_content.key_findings, list) and len(final_content.key_findings) > 0
    assert isinstance(final_content.summary, str) and len(final_content.summary.strip()) > 0
    assert final_content.confidence_level in ["High", "Medium", "Low"]


@pytest.mark.asyncio
async def test_async_tool_use_with_structured_output_stream():
    """Test async streaming tool use combined with structured output."""

    async def get_research_data(topic: str) -> str:
        """Get research data for a given topic."""
        return f"Research findings on {topic}: This topic has multiple aspects including technical implementations, best practices, current trends, and future prospects in the field."

    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
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

        if event.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(event, "tool") and event.tool:  # type: ignore
            if event.tool.tool_name:  # type: ignore
                tool_call_seen = True

        if hasattr(event, "content") and event.content is not None and isinstance(event.content, ResearchSummary):
            final_content = event.content

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in async stream"

    assert final_content is not None
    assert isinstance(final_content, ResearchSummary)

    assert isinstance(final_content.topic, str) and len(final_content.topic.strip()) > 0
    assert isinstance(final_content.key_findings, list) and len(final_content.key_findings) > 0
    assert isinstance(final_content.summary, str) and len(final_content.summary.strip()) > 0
    assert final_content.confidence_level in ["High", "Medium", "Low"]
