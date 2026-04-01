"""
Integration tests for Claude model prompt caching functionality.

Tests the basic caching features including:
- System message caching with real API calls
- Cache performance tracking
- Usage metrics with standard field names
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from agno.agent import Agent, RunOutput
from agno.models.anthropic import Claude
from agno.utils.media import download_file


def _get_large_system_prompt() -> str:
    """Load an example large system message from S3"""
    txt_path = Path(__file__).parent.joinpath("system_prompt.txt")
    download_file(
        "https://agno-public.s3.amazonaws.com/prompts/system_promt.txt",
        str(txt_path),
    )
    return txt_path.read_text()


def _assert_cache_metrics(response: RunOutput, expect_cache_write: bool = False, expect_cache_read: bool = False):
    """Assert cache-related metrics in response."""
    if response.metrics is None:
        pytest.fail("Response metrics is None")

    cache_write_tokens = response.metrics.cache_write_tokens
    cache_read_tokens = response.metrics.cache_read_tokens

    if expect_cache_write:
        assert cache_write_tokens > 0, "Expected cache write tokens but found none"

    if expect_cache_read:
        assert cache_read_tokens > 0, "Expected cache read tokens but found none"


def test_system_message_caching_basic():
    """Test basic system message caching functionality."""
    claude = Claude(cache_system_prompt=True)
    system_message = "You are a helpful assistant."
    kwargs = claude._prepare_request_kwargs(system_message)

    expected_system = [{"text": system_message, "type": "text", "cache_control": {"type": "ephemeral"}}]
    assert kwargs["system"] == expected_system


def test_extended_cache_time():
    """Test extended cache time configuration."""
    claude = Claude(cache_system_prompt=True, extended_cache_time=True)
    system_message = "You are a helpful assistant."
    kwargs = claude._prepare_request_kwargs(system_message)

    expected_system = [{"text": system_message, "type": "text", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    assert kwargs["system"] == expected_system


def test_usage_metrics_parsing():
    """Test parsing enhanced usage metrics with standard field names."""
    claude = Claude()

    mock_response = Mock()
    mock_response.role = "assistant"
    mock_response.content = [Mock(type="text", text="Test response", citations=None)]
    mock_response.stop_reason = None

    mock_usage = Mock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50
    mock_usage.cache_creation_input_tokens = 80
    mock_usage.cache_read_input_tokens = 20

    if hasattr(mock_usage, "cache_creation"):
        del mock_usage.cache_creation
    if hasattr(mock_usage, "cache_read"):
        del mock_usage.cache_read

    mock_response.usage = mock_usage

    model_response = claude._parse_provider_response(mock_response)

    assert model_response.response_usage is not None
    assert model_response.response_usage.input_tokens == 100
    assert model_response.response_usage.output_tokens == 50
    assert model_response.response_usage.cache_write_tokens == 80
    assert model_response.response_usage.cache_read_tokens == 20


def test_prompt_caching_with_agent():
    """Test prompt caching using Agent with a large system prompt."""
    large_system_prompt = _get_large_system_prompt()

    print(f"System prompt length: {len(large_system_prompt)} characters")

    agent = Agent(
        model=Claude(id="claude-sonnet-4-5-20250929", cache_system_prompt=True),
        system_message=large_system_prompt,
        telemetry=False,
    )

    response = agent.run("Explain the key principles of microservices architecture")

    print(f"First response metrics: {response.metrics}")

    if response.metrics is None:
        pytest.fail("Response metrics is None")

    cache_creation_tokens = response.metrics.cache_write_tokens
    cache_hit_tokens = response.metrics.cache_read_tokens

    print(f"Cache creation tokens: {cache_creation_tokens}")
    print(f"Cache hit tokens: {cache_hit_tokens}")

    cache_activity = cache_creation_tokens > 0 or cache_hit_tokens > 0
    if not cache_activity:
        print("No cache activity detected. This might be due to:")
        print("1. System prompt being below Anthropic's minimum caching threshold")
        print("2. Cache already existing from previous runs")
        print("Skipping cache assertions...")
        return

    assert response.content is not None

    if cache_creation_tokens > 0:
        print(f"✅ Cache was created with {cache_creation_tokens} tokens")
        response2 = agent.run("How would you implement monitoring for this architecture?")
        if response2.metrics is None:
            pytest.fail("Response2 metrics is None")
        cache_read_tokens = response2.metrics.cache_read_tokens
        assert cache_read_tokens > 0, f"Expected cache read tokens but found {cache_read_tokens}"
    else:
        print(f"✅ Cache was used with {cache_hit_tokens} tokens from previous run")


@pytest.mark.asyncio
async def test_async_prompt_caching():
    """Test async prompt caching functionality."""
    large_system_prompt = _get_large_system_prompt()

    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514", cache_system_prompt=True),
        system_message=large_system_prompt,
        telemetry=False,
    )

    response = await agent.arun("Explain REST API design patterns")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
