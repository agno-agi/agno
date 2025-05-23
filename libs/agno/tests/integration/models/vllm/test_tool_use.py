import os
from typing import Optional

import pytest

from agno.agent import Agent, RunResponse
from agno.models.vllm.vllm import Vllm
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.yfinance import YFinanceTools

# Skip the module if no vLLM endpoint configured
if not os.getenv("VLLM_BASE_URL"):
    pytest.skip("VLLM_BASE_URL not set, skipping vLLM tool-use tests", allow_module_level=True)

VLLM_MODEL_ID = os.getenv("VLLM_MODEL_ID", "microsoft/Phi-3-mini-128k-instruct")


def _mk_agent(tool_list):
    return Agent(
        model=Vllm(id=VLLM_MODEL_ID),
        tools=tool_list,
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )


def _assert_tool_called(messages):
    assert any(m.tool_calls for m in messages)


def test_tool_use_single():
    agent = _mk_agent([YFinanceTools(cache_results=True)])
    resp = agent.run("What is the current price of TSLA?")
    _assert_tool_called(resp.messages)
    assert resp.content and "TSLA" in resp.content


def test_tool_use_stream():
    agent = _mk_agent([YFinanceTools(cache_results=True)])
    stream = agent.run("What is the current price of TSLA?", stream=True, stream_intermediate_steps=True)

    saw_tool = False
    for chunk in stream:
        assert isinstance(chunk, RunResponse)
        if chunk.tools and any(tc.get("tool_name") for tc in chunk.tools):
            saw_tool = True
    assert saw_tool


@pytest.mark.asyncio
async def test_tool_use_async():
    agent = _mk_agent([YFinanceTools(cache_results=True)])
    resp = await agent.arun("What is the current price of TSLA?")
    _assert_tool_called(resp.messages)


@pytest.mark.asyncio
async def test_tool_use_async_stream():
    agent = _mk_agent([YFinanceTools(cache_results=True)])
    stream = await agent.arun("What is the current price of TSLA?", stream=True, stream_intermediate_steps=True)
    saw_tool = False
    async for chunk in stream:
        if chunk.tools and any(tc.get("tool_name") for tc in chunk.tools):
            saw_tool = True
    assert saw_tool


def test_parallel_tool_calls():
    agent = _mk_agent([YFinanceTools(cache_results=True)])
    resp = agent.run("What is the current price of TSLA and AAPL?")
    # expect 2 tool calls
    calls = [tc for m in resp.messages if m.tool_calls for tc in m.tool_calls]
    assert len([c for c in calls if c.get("type") == "function"]) == 2


def test_multiple_tool_calls():
    agent = _mk_agent([YFinanceTools(cache_results=True), DuckDuckGoTools(cache_results=True)])
    resp = agent.run("What is the current price of TSLA and the latest news about it?")
    _assert_tool_called(resp.messages)
    assert resp.content and "TSLA" in resp.content


def test_custom_tool_optional_param():
    def get_weather(city: Optional[str] = None):
        """Simple demo function"""
        return f"Weather for {city or 'Tokyo'} is 20C"

    agent = _mk_agent([get_weather])
    resp = agent.run("What is the weather in Paris?")
    _assert_tool_called(resp.messages)
    assert "Paris" in resp.content


def test_list_param_tool():
    agent = _mk_agent([ExaTools()])
    resp = agent.run(
        "What are the papers at https://arxiv.org/pdf/2307.06435 and https://arxiv.org/pdf/2502.09601 about?"
    )
    _assert_tool_called(resp.messages)
