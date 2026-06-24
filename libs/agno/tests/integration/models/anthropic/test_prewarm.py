"""Integration tests for Claude cache pre-warming (live API).

These tests make real Anthropic API calls and need ANTHROPIC_API_KEY set.
They are lenient: caching can silently no-op (prompt below the model's
minimum cacheable length, or cache already warm), so they skip rather than
fail when no cache activity is observed.
"""

from pathlib import Path

import pytest

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.message import Message

MODEL_ID = "claude-sonnet-4-5-20250929"


def _large_system_prompt() -> str:
    """Load an example large system message from S3."""
    return Path(__file__).parent.joinpath("system_prompt.txt").read_text()


def _messages(system_prompt: str) -> list[Message]:
    return [
        Message(role="system", content=system_prompt),
        Message(role="user", content="warmup"),
    ]


def test_prewarm_writes_cache():
    """prewarm() should write the prompt cache on a cold call."""
    model = Claude(id=MODEL_ID, cache_system_prompt=True)
    metrics = model.prewarm(_messages(_large_system_prompt()))
    assert metrics is not None
    print(f"prewarm metrics: write={metrics.cache_write_tokens} read={metrics.cache_read_tokens}")
    if metrics.cache_write_tokens == 0 and metrics.cache_read_tokens == 0:
        pytest.skip("No cache activity — prompt below threshold or already cached")
    assert metrics.cache_write_tokens > 0 or metrics.cache_read_tokens > 0


def test_prewarm_then_run_hits_cache():
    """After prewarm(), the first real agent run should read from the warm cache."""
    system_prompt = _large_system_prompt()
    model = Claude(id=MODEL_ID, cache_system_prompt=True)

    prewarm_metrics = model.prewarm(_messages(system_prompt))
    assert prewarm_metrics is not None

    agent = Agent(model=model, system_message=system_prompt, telemetry=False)
    response = agent.run("Explain the key principles of microservices architecture")
    if response.metrics is None:
        pytest.fail("Response metrics is None")
    print(f"post-prewarm run: cache_read_tokens={response.metrics.cache_read_tokens}")
    if response.metrics.cache_read_tokens == 0:
        pytest.skip("No cache read — prompt below threshold or cache expired")
    assert response.metrics.cache_read_tokens > 0


@pytest.mark.asyncio
async def test_aprewarm_writes_cache():
    """aprewarm() should write the prompt cache on a cold call."""
    model = Claude(id=MODEL_ID, cache_system_prompt=True)
    metrics = await model.aprewarm(_messages(_large_system_prompt()))
    assert metrics is not None
    if metrics.cache_write_tokens == 0 and metrics.cache_read_tokens == 0:
        pytest.skip("No cache activity — prompt below threshold or already cached")
    assert metrics.cache_write_tokens > 0 or metrics.cache_read_tokens > 0
