"""
Integration tests for Claude model prompt caching functionality.

Tests the enhanced caching features including:
- System message caching with real API calls
- Tool definition caching
- Cache performance tracking
- Enhanced usage metrics with official field names
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agno.agent import Agent, RunResponse
from agno.models.anthropic import Claude
from agno.utils.log import log_warning
from agno.utils.media import download_file


def _get_large_system_prompt() -> str:
    """Load an example large system message from S3"""
    txt_path = Path(__file__).parent.joinpath("system_prompt.txt")
    download_file(
        "https://agno-public.s3.amazonaws.com/prompts/system_promt.txt",
        str(txt_path),
    )
    return txt_path.read_text()


def _assert_cache_metrics(response: RunResponse, expect_cache_write: bool = False, expect_cache_read: bool = False):
    """Assert cache-related metrics in response."""
    cache_write_tokens = response.metrics.get("cache_creation_input_tokens", [0])
    cache_read_tokens = response.metrics.get("cache_read_input_tokens", [0])

    if expect_cache_write:
        assert sum(cache_write_tokens) > 0, "Expected cache write tokens but found none"

    if expect_cache_read:
        assert sum(cache_read_tokens) > 0, "Expected cache read tokens but found none"


def test_cache_control_creation():
    """Test cache control creation with different configurations."""
    # Default 5-minute cache
    claude_5m = Claude(cache_system_prompt=True)
    cache_control = claude_5m._create_cache_control()
    assert cache_control == {"type": "ephemeral"}

    # 1-hour cache
    claude_1h = Claude(cache_ttl="1h")
    cache_control = claude_1h._create_cache_control()
    assert cache_control == {"type": "ephemeral", "ttl": "1h"}


def test_beta_headers():
    """Test that proper beta headers are set for caching."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        # 5-minute cache
        claude_5m = Claude(cache_system_prompt=True, cache_ttl="5m")
        params_5m = claude_5m._get_client_params()
        assert params_5m["default_headers"]["anthropic-beta"] == "prompt-caching-2024-07-31"

        # 1-hour cache
        claude_1h = Claude(cache_ttl="1h")
        params_1h = claude_1h._get_client_params()
        assert (
            params_1h["default_headers"]["anthropic-beta"] == "prompt-caching-2024-07-31,extended-cache-ttl-2025-04-11"
        )


def test_system_message_caching_basic():
    """Test basic system message caching functionality."""
    claude = Claude(cache_system_prompt=True)
    system_message = "You are a helpful assistant."
    kwargs = claude._prepare_request_kwargs(system_message)

    expected_system = [{"text": system_message, "type": "text", "cache_control": {"type": "ephemeral"}}]
    assert kwargs["system"] == expected_system


def test_tool_caching():
    """Test tool definition caching."""
    claude = Claude(cache_tool_definitions=True)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_tool",
                "description": "A search tool",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Search query"}},
                    "required": ["query"],
                },
            },
        }
    ]

    kwargs = claude._prepare_request_kwargs("system", tools)

    assert "cache_control" in kwargs["tools"][-1]
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_usage_metrics_parsing():
    """Test parsing enhanced usage metrics with official field names."""
    claude = Claude()

    # Mock response with cache metrics
    mock_response = Mock()
    mock_response.role = "assistant"
    mock_response.content = [Mock(type="text", text="Test response", citations=None)]
    mock_response.stop_reason = None

    mock_usage = Mock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50
    mock_usage.cache_creation_input_tokens = 80
    mock_usage.cache_read_input_tokens = 20

    # Remove extra attributes that might interfere
    if hasattr(mock_usage, "cache_creation"):
        del mock_usage.cache_creation
    if hasattr(mock_usage, "cache_read"):
        del mock_usage.cache_read

    mock_response.usage = mock_usage

    model_response = claude.parse_provider_response(mock_response)

    expected_usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 80,
        "cache_read_input_tokens": 20,
    }
    assert model_response.response_usage == expected_usage


def test_cache_performance_logging():
    """Test cache performance logging functionality."""
    claude = Claude()

    usage_metrics = {
        "input_tokens": 50,
        "output_tokens": 100,
        "cache_creation_input_tokens": 200,
        "cache_read_input_tokens": 150,
    }

    # This should not raise any exceptions
    claude.log_cache_performance(usage_metrics, debug=False)
    claude.log_cache_performance(usage_metrics, debug=True)


def test_prompt_caching_with_agent():
    """Test prompt caching using Agent with a large system prompt."""
    large_system_prompt = _get_large_system_prompt()

    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022", cache_system_prompt=True),
        system_message=large_system_prompt,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Explain the key principles of microservices architecture")

    # This test needs a clean Anthropic cache to run. If the cache is not empty, we skip the test.
    if response.metrics.get("cache_read_input_tokens", [0])[0] > 0:
        log_warning(
            "A cache is already active in this Anthropic context. This test can't run until the cache is cleared."
        )
        return

    # Assert the system prompt is cached on the first run
    assert response.content is not None
    cache_creation_tokens = response.metrics.get("cache_creation_input_tokens", [0])[0]
    assert cache_creation_tokens > 0, "Expected cache creation tokens but found none"

    # Run second request to test cache hit
    response2 = agent.run("What are the benefits of using containers in microservices?")

    # Assert the cached prompt is used on the second run
    assert response2.content is not None
    cache_read_tokens = response2.metrics.get("cache_read_input_tokens", [0])[0]
    assert cache_read_tokens > 0, "Expected cache read tokens but found none"

    # Verify cache hit matches cache creation
    assert cache_read_tokens == cache_creation_tokens, (
        f"Cache read ({cache_read_tokens}) should match cache creation ({cache_creation_tokens})"
    )


@pytest.mark.asyncio
async def test_async_prompt_caching():
    """Test async prompt caching functionality."""
    large_system_prompt = _get_large_system_prompt()

    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022", cache_system_prompt=True),
        system_message=large_system_prompt,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("Explain REST API design patterns")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]


def test_comprehensive_caching_config():
    """Test comprehensive caching configuration with multiple features."""
    agent = Agent(
        model=Claude(
            id="claude-3-5-haiku-20241022", cache_system_prompt=True, cache_tool_definitions=True, cache_ttl="1h"
        ),
        system_message="You are an expert software architect.",
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Design a scalable web application architecture")

    assert response.content is not None
    assert len(response.messages) == 3


def test_caching_with_tools():
    """Test caching functionality when using tools."""
    from agno.tools.python import PythonTools

    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022", cache_system_prompt=True, cache_tool_definitions=True),
        tools=[PythonTools()],
        system_message="You are a helpful coding assistant.",
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Calculate the fibonacci sequence for n=10")

    assert response.content is not None
    # Verify tool was used
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls)


@pytest.mark.skip(reason="Requires API key and can be expensive - for manual testing")
def test_real_cache_performance():
    """
    Real performance test showing cache benefits.

    Run manually with: pytest -k test_real_cache_performance -s
    """
    # Very large system prompt to guarantee caching
    large_system_prompt = (
        """You are an expert enterprise software architect and technical consultant with over 20 years of experience in designing, implementing, and scaling large-scale distributed systems. Your expertise spans across multiple domains including microservices architecture, cloud computing, DevOps practices, database design, API development, security architecture, and performance optimization. You provide detailed, practical guidance based on industry best practices and real-world experience."""
        * 10
    )

    agent = Agent(
        model=Claude(id="claude-3-5-sonnet-20241022", cache_system_prompt=True, cache_ttl="5m"),
        system_message=large_system_prompt,
        telemetry=False,
        monitoring=False,
    )

    print(f"System prompt length: {len(large_system_prompt)} characters")

    # First call - should create cache
    import time

    start1 = time.time()
    response1 = agent.run("Design a microservices architecture for an e-commerce platform")
    end1 = time.time()

    print(f"First call time: {end1 - start1:.2f}s")
    print(f"First call metrics: {response1.metrics}")

    # Second call - should hit cache
    time.sleep(1)
    start2 = time.time()
    response2 = agent.run("How would you implement monitoring for this architecture?")
    end2 = time.time()

    print(f"Second call time: {end2 - start2:.2f}s")
    print(f"Second call metrics: {response2.metrics}")

    # Verify caching worked
    cache_created = response1.metrics.get("cache_creation_input_tokens", [0])[0]
    cache_hit = response2.metrics.get("cache_read_input_tokens", [0])[0]

    assert cache_created > 0, "Cache should have been created"
    assert cache_hit > 0, "Cache should have been hit"
    print(f"✅ Caching working: {cache_created} tokens cached, {cache_hit} tokens reused")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
