import pytest

from agno.agent import Agent, RunResponse
from agno.models.huggingface import HuggingFace
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.yfinance import YFinanceTools


def test_tool_use():
    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "TSLA" in response.content


@pytest.mark.skip(reason="Huggingface right now doesn't support streaming tool calls")
def test_tool_use_stream():
    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response_stream = agent.run("What is the current price of TSLA?", stream=True)

    responses = []
    tool_call_seen = False

    for chunk in response_stream:
        assert isinstance(chunk, RunResponse)
        responses.append(chunk)
        if chunk.tools:
            if any(tc.get("tool_name") for tc in chunk.tools):
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    assert any("TSLA" in r.content for r in responses if r.content)


@pytest.mark.asyncio
async def test_async_tool_use():
    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("What is the current price of TSLA?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant")
    assert response.content is not None
    assert "TSLA" in response.content


@pytest.mark.skip(reason="Huggingface right now doesn't support streaming tool calls")
@pytest.mark.asyncio
async def test_async_tool_use_stream():
    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response_stream = await agent.arun("What is the current price of TSLA?", stream=True)

    responses = []
    tool_call_seen = False

    async for chunk in response_stream:
        assert isinstance(chunk, RunResponse)
        responses.append(chunk)
        if chunk.tools:
            if any(tc.get("tool_name") for tc in chunk.tools):
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    assert any("TSLA" in r.content for r in responses if r.content)


@pytest.mark.skip(reason="This test fails as HuggingFace calls the tools more than once for each tool")
def test_parallel_tool_calls():
    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the current price of TSLA and AAPL?")

    # Verify tool usage
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls]
    assert len(tool_calls) >= 1  # At least one message has tool calls
    assert sum(len(calls) for calls in tool_calls) == 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content and "AAPL" in response.content


@pytest.mark.skip(reason="This test fails as HuggingFace calls the tools more than once for each tool")
def test_multiple_tool_calls():
    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        tools=[YFinanceTools(cache_results=True), DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the current price of TSLA and what is the latest news about it?")

    # Verify tool usage
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls]
    assert len(tool_calls) >= 1  # At least one message has tool calls
    assert sum(len(calls) for calls in tool_calls) == 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content and "latest news" in response.content.lower()


def test_tool_call_custom_tool_no_parameters():
    def get_the_weather():
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        tools=[get_the_weather],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "70" in response.content


@pytest.mark.skip(reason="Right now HuggingFace implementation doesn't support tool calls with list parameters")
def test_tool_call_list_parameters():
    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        tools=[ExaTools()],
        instructions="Use a single tool call if possible",
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run(
        "What are the papers at https://arxiv.org/pdf/2307.06435 and https://arxiv.org/pdf/2502.09601 about?"
    )

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        assert call["function"]["name"] in ["get_contents", "exa_answer"]
    assert response.content is not None
