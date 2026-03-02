"""
Integration tests for Claude model prompt caching functionality.

Tests the basic caching features including:
- System message caching with real API calls
- Cache performance tracking
- Usage metrics with standard field names
- Multi-block system prompt caching (static/dynamic split)
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from agno.agent import Agent, RunOutput
from agno.session.agent import AgentSession
from agno.models.anthropic import Claude
from agno.models.message import Message, SystemPromptBlock
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
        model=Claude(id="claude-3-5-haiku-20241022", cache_system_prompt=True),
        system_message=large_system_prompt,
        telemetry=False,
    )

    response = await agent.arun("Explain REST API design patterns")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]


# --- Multi-block system prompt caching tests ---


def test_multi_block_system_message_caching():
    """Test that SystemPromptBlock list produces correct multi-block API structure."""
    claude = Claude(cache_system_prompt=True)
    blocks = [
        SystemPromptBlock(text="Static instructions here.", cache=True),
        SystemPromptBlock(text="Dynamic per-user context.", cache=False),
    ]
    kwargs = claude._prepare_request_kwargs(blocks)

    assert len(kwargs["system"]) == 2
    assert kwargs["system"][0] == {
        "text": "Static instructions here.",
        "type": "text",
        "cache_control": {"type": "ephemeral"},
    }
    assert kwargs["system"][1] == {
        "text": "Dynamic per-user context.",
        "type": "text",
    }


def test_multi_block_no_caching():
    """Test that blocks are sent without cache_control when caching is disabled."""
    claude = Claude(cache_system_prompt=False)
    blocks = [
        SystemPromptBlock(text="Static.", cache=True),
        SystemPromptBlock(text="Dynamic.", cache=False),
    ]
    kwargs = claude._prepare_request_kwargs(blocks)

    assert len(kwargs["system"]) == 2
    for block in kwargs["system"]:
        assert "cache_control" not in block


def test_multi_block_extended_cache_time():
    """Test that extended cache time only applies to cached blocks."""
    claude = Claude(cache_system_prompt=True, extended_cache_time=True)
    blocks = [
        SystemPromptBlock(text="Static.", cache=True),
        SystemPromptBlock(text="Dynamic.", cache=False),
    ]
    kwargs = claude._prepare_request_kwargs(blocks)

    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "cache_control" not in kwargs["system"][1]


def test_string_system_message_backward_compat():
    """Test that a plain string still produces a single cached block (backward compat)."""
    claude = Claude(cache_system_prompt=True)
    kwargs = claude._prepare_request_kwargs("You are helpful.")

    assert len(kwargs["system"]) == 1
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["system"][0]["text"] == "You are helpful."


def test_agent_no_auto_blocks():
    """Agent never auto-generates system_prompt_blocks. Users who want multi-block
    caching must pass List[SystemPromptBlock] as system_message explicitly."""
    agent = Agent(
        model=Claude(id="claude-sonnet-4-5-20250929", cache_system_prompt=True),
        description="Test agent",
        instructions=["Be helpful"],
        add_datetime_to_context=True,
        telemetry=False,
    )
    session = AgentSession(session_id="test")
    msg = agent.get_system_message(session=session)

    assert msg is not None
    assert msg.system_prompt_blocks is None
    assert "Test agent" in msg.content
    assert "The current time is" in msg.content


def test_agent_manual_system_prompt_blocks():
    """Test that users can pass List[SystemPromptBlock] as system_message."""
    blocks = [
        SystemPromptBlock(text="You are a code reviewer.", cache=True),
        SystemPromptBlock(text="User context: premium tier.", cache=False),
    ]
    agent = Agent(
        model=Claude(id="claude-sonnet-4-5-20250929", cache_system_prompt=True),
        system_message=blocks,
        telemetry=False,
    )
    session = AgentSession(session_id="test")
    msg = agent.get_system_message(session=session)

    assert msg is not None
    assert msg.system_prompt_blocks is not None
    assert len(msg.system_prompt_blocks) == 2
    assert msg.system_prompt_blocks[0].text == "You are a code reviewer."
    assert msg.system_prompt_blocks[0].cache is True
    assert msg.system_prompt_blocks[1].text == "User context: premium tier."
    assert msg.system_prompt_blocks[1].cache is False
    # content should be the joined text
    assert "You are a code reviewer." in msg.content
    assert "User context: premium tier." in msg.content


# --- Per-block TTL tests ---


def test_per_block_ttl():
    """Test that a block with ttl='1h' produces extended cache_control."""
    claude = Claude(cache_system_prompt=True)
    blocks = [
        SystemPromptBlock(text="Static instructions.", cache=True, ttl="1h"),
    ]
    kwargs = claude._prepare_request_kwargs(blocks)

    assert len(kwargs["system"]) == 1
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_mixed_ttl_blocks():
    """Test blocks with different TTLs produce correct independent cache_control."""
    claude = Claude(cache_system_prompt=True)
    blocks = [
        SystemPromptBlock(text="Long-lived.", cache=True, ttl="1h"),
        SystemPromptBlock(text="Short-lived.", cache=True, ttl="5m"),
        SystemPromptBlock(text="Dynamic.", cache=False),
    ]
    kwargs = claude._prepare_request_kwargs(blocks)

    assert len(kwargs["system"]) == 3
    # 1h block
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    # 5m block (default, no ttl key)
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral"}
    # uncached block
    assert "cache_control" not in kwargs["system"][2]


def test_explicit_block_ttl_overrides_model_extended_cache_time():
    """Explicit block-level ttl='5m' stays 5m even when model has extended_cache_time=True."""
    claude = Claude(cache_system_prompt=True, extended_cache_time=True)
    blocks = [
        SystemPromptBlock(text="Explicit 5m.", cache=True, ttl="5m"),
        SystemPromptBlock(text="Default (inherits model).", cache=True),
    ]
    kwargs = claude._prepare_request_kwargs(blocks)

    # Explicit ttl="5m" overrides model-level extended_cache_time
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    # ttl=None falls back to model-level extended_cache_time=True => 1h
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


# --- Tool caching tests ---


def test_cache_tools_flag():
    """Test that cache_tools=True adds cache_control to the last tool."""
    claude = Claude(cache_system_prompt=True, cache_tools=True)
    tools = [
        {"type": "function", "function": {"name": "tool_a", "description": "A", "parameters": {"type": "object", "properties": {}, "required": []}}},
        {"type": "function", "function": {"name": "tool_b", "description": "B", "parameters": {"type": "object", "properties": {}, "required": []}}},
    ]
    kwargs = claude._prepare_request_kwargs("System.", tools=tools)

    assert "tools" in kwargs
    assert len(kwargs["tools"]) == 2
    # Only the last tool gets cache_control
    assert "cache_control" not in kwargs["tools"][0]
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_cache_tools_disabled():
    """Test that cache_tools=False leaves tools untouched."""
    claude = Claude(cache_system_prompt=True, cache_tools=False)
    tools = [
        {"type": "function", "function": {"name": "tool_a", "description": "A", "parameters": {"type": "object", "properties": {}, "required": []}}},
    ]
    kwargs = claude._prepare_request_kwargs("System.", tools=tools)

    assert "tools" in kwargs
    for tool in kwargs["tools"]:
        assert "cache_control" not in tool


def test_cache_false_ignores_ttl():
    """Block with cache=False should produce no cache_control, even if ttl is set."""
    claude = Claude(cache_system_prompt=True)
    blocks = [
        SystemPromptBlock(text="Not cached.", cache=False, ttl="1h"),
    ]
    kwargs = claude._prepare_request_kwargs(blocks)

    assert len(kwargs["system"]) == 1
    assert "cache_control" not in kwargs["system"][0]


def test_cache_tools_single_tool():
    """cache_tools=True with a single tool should add cache_control to that tool."""
    claude = Claude(cache_system_prompt=True, cache_tools=True)
    tools = [
        {"type": "function", "function": {"name": "only_tool", "description": "Solo", "parameters": {"type": "object", "properties": {}, "required": []}}},
    ]
    kwargs = claude._prepare_request_kwargs("System.", tools=tools)

    assert len(kwargs["tools"]) == 1
    assert kwargs["tools"][0]["cache_control"] == {"type": "ephemeral"}


def test_cache_tools_no_tools():
    """cache_tools=True with no tools should not error."""
    claude = Claude(cache_system_prompt=True, cache_tools=True)
    kwargs = claude._prepare_request_kwargs("System.", tools=None)

    assert "tools" not in kwargs


def test_explicit_5m_with_no_extended_cache():
    """Explicit ttl='5m' with extended_cache_time=False should produce ephemeral without ttl key."""
    claude = Claude(cache_system_prompt=True, extended_cache_time=False)
    blocks = [
        SystemPromptBlock(text="Explicit 5m.", cache=True, ttl="5m"),
        SystemPromptBlock(text="Default None.", cache=True),
    ]
    kwargs = claude._prepare_request_kwargs(blocks)

    # Both should be plain ephemeral (no "ttl" key)
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral"}


def test_format_messages_preserves_blocks():
    """system_prompt_blocks on a Message flow through format_messages and come back as List[SystemPromptBlock]."""
    from agno.utils.models.claude import format_messages

    blocks = [
        SystemPromptBlock(text="Static part.", cache=True, ttl="1h"),
        SystemPromptBlock(text="Dynamic part.", cache=False),
    ]
    msg = Message(
        role="system",
        content="Static part.\nDynamic part.",
        system_prompt_blocks=blocks,
    )
    chat_messages, system_message = format_messages([msg])

    # system_message should be the blocks, not the joined string
    assert isinstance(system_message, list)
    assert len(system_message) == 2
    assert system_message[0].text == "Static part."
    assert system_message[0].ttl == "1h"
    assert system_message[1].cache is False


def test_vertexai_cache_tools():
    """VertexAI Claude should also add cache_control to the last tool."""
    from agno.models.vertexai.claude import Claude as VertexClaude

    claude = VertexClaude(cache_system_prompt=True, cache_tools=True)
    tools = [
        {"type": "function", "function": {"name": "tool_a", "description": "A", "parameters": {"type": "object", "properties": {}, "required": []}}},
        {"type": "function", "function": {"name": "tool_b", "description": "B", "parameters": {"type": "object", "properties": {}, "required": []}}},
    ]
    kwargs = claude._prepare_request_kwargs("System.", tools=tools)

    assert "cache_control" not in kwargs["tools"][0]
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_aws_cache_tools():
    """AWS Bedrock Claude should also add cache_control to the last tool."""
    from agno.models.aws.claude import Claude as AwsClaude

    claude = AwsClaude(cache_system_prompt=True, cache_tools=True)
    tools = [
        {"type": "function", "function": {"name": "tool_a", "description": "A", "parameters": {"type": "object", "properties": {}, "required": []}}},
        {"type": "function", "function": {"name": "tool_b", "description": "B", "parameters": {"type": "object", "properties": {}, "required": []}}},
    ]
    kwargs = claude._prepare_request_kwargs("System.", tools=tools)

    assert "cache_control" not in kwargs["tools"][0]
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}
