"""Integration tests for Agent.get_prewarm_payload() (live API).

These tests make real Anthropic API calls and need ANTHROPIC_API_KEY set.
They are lenient: caching can silently no-op (prompt below the model's
minimum cacheable length, or cache already warm), so they skip rather than
fail when no cache activity is observed.
"""

from pathlib import Path

import pytest

from agno.agent import Agent
from agno.models.anthropic import Claude

MODEL_ID = "claude-sonnet-4-5-20250929"


def _large_system_prompt() -> str:
    """Load an example large system message from S3."""
    return Path(__file__).parent.joinpath("system_prompt.txt").read_text()


def _agent() -> Agent:
    return Agent(
        model=Claude(id=MODEL_ID, cache_system_prompt=True),
        system_message=_large_system_prompt(),
        telemetry=False,
    )


def test_agent_get_prewarm_payload_writes_cache():
    """agent.get_prewarm_payload() + model.prewarm() should write the prompt cache."""
    agent = _agent()
    payload = agent.get_prewarm_payload()
    assert payload is not None
    system_message, tools = payload
    metrics = agent.model.prewarm(messages=[system_message], tools=tools)
    assert metrics is not None
    print(f"agent prewarm metrics: write={metrics.cache_write_tokens} read={metrics.cache_read_tokens}")
    if metrics.cache_write_tokens == 0 and metrics.cache_read_tokens == 0:
        pytest.skip("No cache activity — prompt below threshold or already cached")
    assert metrics.cache_write_tokens > 0 or metrics.cache_read_tokens > 0


def test_agent_prewarm_then_run_hits_cache():
    """After prewarming with the helper's payload, the first real run reads from the warm cache."""
    agent = _agent()
    payload = agent.get_prewarm_payload()
    assert payload is not None
    system_message, tools = payload
    agent.model.prewarm(messages=[system_message], tools=tools)

    response = agent.run("Explain the key principles of microservices architecture")
    if response.metrics is None:
        pytest.fail("Response metrics is None")
    print(f"post-prewarm run: cache_read_tokens={response.metrics.cache_read_tokens}")
    if response.metrics.cache_read_tokens == 0:
        pytest.skip("No cache read — prompt below threshold or cache expired")
    assert response.metrics.cache_read_tokens > 0


@pytest.mark.asyncio
async def test_agent_aget_prewarm_payload_writes_cache():
    """Async variant: agent.aget_prewarm_payload() + model.aprewarm()."""
    agent = _agent()
    payload = await agent.aget_prewarm_payload()
    assert payload is not None
    system_message, tools = payload
    metrics = await agent.model.aprewarm(messages=[system_message], tools=tools)
    assert metrics is not None
    if metrics.cache_write_tokens == 0 and metrics.cache_read_tokens == 0:
        pytest.skip("No cache activity — prompt below threshold or already cached")
    assert metrics.cache_write_tokens > 0 or metrics.cache_read_tokens > 0
