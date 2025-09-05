import pytest

from agno.agent import Agent
from agno.models.huggingface import HuggingFace
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.yfinance import YFinanceTools


def test_tool_use():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert response.content is not None
    assert "TSLA" in response.content


def test_tool_use_stream():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response_stream = agent.run("What is the current price of TSLA?", stream=True, stream_intermediate_steps=True)

    responses = []
    tool_call_seen = False

    for chunk in response_stream:
        responses.append(chunk)
        if chunk.content:
            if "TSLA" in chunk.content:
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"


@pytest.mark.asyncio
async def test_async_tool_use():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert response.content is not None
    assert "TSLA" in response.content


@pytest.mark.asyncio
async def test_async_tool_use_stream():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    async for response in agent.arun(
        "What is the current price of TSLA?",
        stream=True,
        stream_intermediate_steps=True,
    ):
        if response.content:
            if "TSLA" in response.content:
                tool_call_seen = True

    assert tool_call_seen, "No tool calls observed in stream"


def test_parallel_tool_calls():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and AAPL?")

    # Verify tool usage
    assert response.messages is not None
    assert response.content is not None
    assert "TSLA" in response.content and "AAPL" in response.content


def test_multiple_tool_calls():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"),
        tools=[YFinanceTools(cache_results=True), DuckDuckGoTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and what is the latest news about it?")

    # Verify tool usage
    assert response.messages is not None
    assert response.content is not None
    assert "TSLA" in response.content and "latest news" in response.content.lower()


def test_tool_call_custom_tool_no_parameters():
    def get_the_weather():
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    # Verify tool usage
    assert response.messages is not None
    assert response.content is not None


def test_tool_call_list_parameters():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"),
        tools=[ExaTools()],
        instructions="Use a single tool call if possible",
        markdown=True,
        telemetry=False,
    )

    response = agent.run(
        "What are the papers at https://arxiv.org/pdf/2307.06435 and https://arxiv.org/pdf/2502.09601 about?"
    )

    # Verify tool usage
    assert response.messages is not None
    assert response.content is not None
