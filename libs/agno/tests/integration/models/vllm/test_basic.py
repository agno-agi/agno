import os

import pytest

from agno.agent import Agent, RunResponse
from agno.exceptions import ModelProviderError
from agno.models.vllm.vllm import Vllm

# Skip all vLLM tests if no base URL is configured
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL")
if not VLLM_BASE_URL:
    pytest.skip("VLLM_BASE_URL not set, skipping vLLM integration tests", allow_module_level=True)

# Use default model id or override via env var
VLLM_MODEL_ID = os.getenv("VLLM_MODEL_ID", "microsoft/Phi-3-mini-128k-instruct")


def _assert_common(response: RunResponse):
    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]


def test_basic():
    agent = Agent(model=Vllm(id=VLLM_MODEL_ID), markdown=True, telemetry=False, monitoring=False)
    response: RunResponse = agent.run("Test vLLM integration")
    _assert_common(response)


def test_stream():
    agent = Agent(model=Vllm(id=VLLM_MODEL_ID), markdown=True, telemetry=False, monitoring=False)
    response_stream = agent.run("Test vLLM integration", stream=True)
    assert hasattr(response_stream, "__iter__")
    responses = list(response_stream)
    assert len(responses) > 0
    for resp in responses:
        assert isinstance(resp, RunResponse)
        assert resp.content is not None
    _assert_common(agent.run_response)


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(model=Vllm(id=VLLM_MODEL_ID), markdown=True, telemetry=False, monitoring=False)
    response = await agent.arun("Test vLLM integration")
    _assert_common(response)


@pytest.mark.asyncio
async def test_async_stream():
    agent = Agent(model=Vllm(id=VLLM_MODEL_ID), markdown=True, telemetry=False, monitoring=False)
    response_stream = await agent.arun("Test vLLM integration", stream=True)
    assert hasattr(response_stream, "__aiter__")
    async for resp in response_stream:
        assert isinstance(resp, RunResponse)
        assert resp.content is not None
    _assert_common(agent.run_response)


def test_exception():
    agent = Agent(model=Vllm(id="invalid-model-id"), markdown=True, telemetry=False, monitoring=False)
    with pytest.raises(ModelProviderError):
        agent.run("Test vLLM exception")
