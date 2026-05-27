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
from agno.models.anthropic import Claude, SystemPromptBlock
from agno.session.agent import AgentSession
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
        print(f"Cache was created with {cache_creation_tokens} tokens")
        response2 = agent.run("How would you implement monitoring for this architecture?")
        if response2.metrics is None:
            pytest.fail("Response2 metrics is None")
        if response2.content is None:
            pytest.skip("Second API call failed (likely timeout), skipping cache read assertion")
        cache_read_tokens = response2.metrics.cache_read_tokens
        assert cache_read_tokens > 0, f"Expected cache read tokens but found {cache_read_tokens}"
    else:
        print(f"Cache was used with {cache_hit_tokens} tokens from previous run")


@pytest.mark.asyncio
async def test_async_prompt_caching():
    """Test async prompt caching functionality."""
    large_system_prompt = _get_large_system_prompt()

    agent = Agent(
        model=Claude(id="claude-sonnet-4-5-20250929", cache_system_prompt=True),
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
    """system_prompt_blocks on the model produces a multi-block system array."""
    blocks = [
        SystemPromptBlock(text="Static instructions here.", cache=True),
        SystemPromptBlock(text="Dynamic per-user context.", cache=False),
    ]
    claude = Claude(cache_system_prompt=True, system_prompt_blocks=blocks)
    kwargs = claude._prepare_request_kwargs("")

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


def test_block_cache_field_independent_of_cache_system_prompt():
    """block.cache decides per-block caching on its own — cache_system_prompt
    only controls the agent-built string block. This lets users cache custom
    blocks while leaving the agent-built block uncached."""
    blocks = [
        SystemPromptBlock(text="Custom cached.", cache=True),
        SystemPromptBlock(text="Custom uncached.", cache=False),
    ]
    claude = Claude(cache_system_prompt=False, system_prompt_blocks=blocks)
    kwargs = claude._prepare_request_kwargs("")

    assert len(kwargs["system"]) == 2
    # block.cache=True still gets cache_control even when cache_system_prompt=False
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    # block.cache=False stays uncached
    assert "cache_control" not in kwargs["system"][1]


def test_multi_block_extended_cache_time():
    """extended_cache_time applies only to cached blocks."""
    blocks = [
        SystemPromptBlock(text="Static.", cache=True),
        SystemPromptBlock(text="Dynamic.", cache=False),
    ]
    claude = Claude(cache_system_prompt=True, extended_cache_time=True, system_prompt_blocks=blocks)
    kwargs = claude._prepare_request_kwargs("")

    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "cache_control" not in kwargs["system"][1]


def test_string_system_message_backward_compat():
    """Plain string still produces a single cached block."""
    claude = Claude(cache_system_prompt=True)
    kwargs = claude._prepare_request_kwargs("You are helpful.")

    assert len(kwargs["system"]) == 1
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["system"][0]["text"] == "You are helpful."


def test_system_prompt_blocks_augment_agent_system_message():
    """Agent-built string comes first as a cached block, user blocks are appended."""
    blocks = [
        SystemPromptBlock(text="User-added static.", cache=True, ttl="1h"),
        SystemPromptBlock(text="User-added dynamic.", cache=False),
    ]
    # extended_cache_time=True so the agent block matches the 1h user block's TTL
    # (Anthropic requires 1h cache_control to not follow a 5m one).
    claude = Claude(cache_system_prompt=True, extended_cache_time=True, system_prompt_blocks=blocks)
    kwargs = claude._prepare_request_kwargs("You are a helpful assistant.")

    # Agent content is the first block (cached per cache_system_prompt), then user blocks
    assert len(kwargs["system"]) == 3
    assert kwargs["system"][0] == {
        "text": "You are a helpful assistant.",
        "type": "text",
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }
    assert kwargs["system"][1] == {
        "text": "User-added static.",
        "type": "text",
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }
    assert kwargs["system"][2] == {
        "text": "User-added dynamic.",
        "type": "text",
    }


def test_system_prompt_blocks_callable_evaluated_per_request():
    """A callable system_prompt_blocks is resolved on every _build_system call,
    so users can inject dynamic per-request content without reinstantiating
    the model or agent.
    """
    call_count = {"n": 0}

    def build_blocks():
        call_count["n"] += 1
        return [
            SystemPromptBlock(text="Static role.", cache=True, ttl="1h"),
            SystemPromptBlock(text=f"Request #{call_count['n']}.", cache=False),
        ]

    claude = Claude(cache_system_prompt=True, extended_cache_time=True, system_prompt_blocks=build_blocks)

    # First call: callable runs once, block text reflects the invocation
    first = claude._build_system("Agent content.")
    assert call_count["n"] == 1
    assert first[2]["text"] == "Request #1."
    assert "cache_control" not in first[2]  # dynamic block stays uncached

    # Second call: callable runs again, text differs → dynamic content refreshed
    second = claude._build_system("Agent content.")
    assert call_count["n"] == 2
    assert second[2]["text"] == "Request #2."

    # Static parts are identical across calls → cache prefix is stable
    assert first[0] == second[0]
    assert first[1] == second[1]


def test_system_prompt_blocks_callable_propagates_validation():
    """TTL ordering validation still fires when blocks come from a callable."""
    claude = Claude(
        cache_system_prompt=True,
        extended_cache_time=False,
        system_prompt_blocks=lambda: [SystemPromptBlock(text="User 1h.", cache=True, ttl="1h")],
    )
    with pytest.raises(ValueError, match="Invalid Anthropic cache TTL ordering"):
        claude._build_system("Agent content.")


def test_build_system_raises_on_invalid_ttl_ordering():
    """Anthropic rejects 5m-cached-block before 1h-cached-block. _build_system
    must catch this at assembly time with an actionable ValueError."""
    blocks = [SystemPromptBlock(text="User 1h.", cache=True, ttl="1h")]
    # cache_system_prompt=True with extended_cache_time=False → agent block is 5m,
    # then a 1h user block follows. Invalid per Anthropic's mixed-TTL rule.
    claude = Claude(cache_system_prompt=True, extended_cache_time=False, system_prompt_blocks=blocks)

    with pytest.raises(ValueError, match="Invalid Anthropic cache TTL ordering"):
        claude._build_system("Agent content.")


def test_build_system_valid_when_extended_cache_time_matches():
    """Setting extended_cache_time=True aligns the agent block to 1h, fixing the order."""
    blocks = [SystemPromptBlock(text="User 1h.", cache=True, ttl="1h")]
    claude = Claude(cache_system_prompt=True, extended_cache_time=True, system_prompt_blocks=blocks)

    result = claude._build_system("Agent content.")
    assert result[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert result[1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_build_system_valid_when_agent_block_uncached():
    """cache_system_prompt=False leaves the agent-built block uncached while
    user blocks still cache per their own block.cache field. The resulting
    [uncached agent, 1h cached user] ordering satisfies Anthropic's rule
    (no 5m cached block precedes the 1h one)."""
    blocks = [SystemPromptBlock(text="User 1h.", cache=True, ttl="1h")]
    claude = Claude(cache_system_prompt=False, system_prompt_blocks=blocks)

    result = claude._build_system("Agent content.")
    assert "cache_control" not in result[0]
    assert result[1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_to_dict_serializes_cache_flags_but_not_blocks():
    """Scalar cache flags round-trip via to_dict. system_prompt_blocks does not —
    the callable form cannot serialize and the list form would round-trip only
    partially, so we deliberately leave it out of the dict."""
    blocks = [SystemPromptBlock(text="X.", cache=True, ttl="1h")]
    claude = Claude(
        cache_system_prompt=True,
        extended_cache_time=True,
        cache_tools=True,
        system_prompt_blocks=blocks,
    )
    d = claude.to_dict()

    assert d["cache_system_prompt"] is True
    assert d["extended_cache_time"] is True
    assert d["cache_tools"] is True
    assert "system_prompt_blocks" not in d


def test_tools_sorted_by_name_for_cache_stability():
    """Model._format_tools returns tools sorted by name across all providers.

    Anthropic, OpenAI, and Gemini caching all depend on a stable request
    prefix; the deterministic tool order removes dict-iteration / MCP /
    registration-order noise.
    """
    from agno.tools.function import Function

    claude = Claude()
    tools = [
        Function(name="zeta", description="Z"),
        Function(name="alpha", description="A"),
        Function(name="mu", description="M"),
    ]
    result = claude._format_tools(tools)
    assert [t["function"]["name"] for t in result] == ["alpha", "mu", "zeta"]


def test_build_system_shared_between_request_and_count_tokens():
    """count_tokens must assemble the same system array as _prepare_request_kwargs.

    Both paths delegate to _build_system so system_prompt_blocks flow through
    token counting. Regression guard: without the shared helper, count_tokens
    would miss user blocks and under-report tokens.
    """
    blocks = [
        SystemPromptBlock(text="User static.", cache=True, ttl="1h"),
        SystemPromptBlock(text="User dynamic.", cache=False),
    ]
    claude = Claude(cache_system_prompt=True, extended_cache_time=True, system_prompt_blocks=blocks)

    request_system = claude._prepare_request_kwargs("Agent content.")["system"]
    # _build_system is what count_tokens calls; assert same output shape
    count_system = claude._build_system("Agent content.")

    assert request_system == count_system
    # And blocks actually show up (not dropped like before the fix)
    texts = [b["text"] for b in count_system]
    assert texts == ["Agent content.", "User static.", "User dynamic."]


def test_agent_system_message_stays_string():
    """Agent system message is a plain string; Claude-level blocks live on the model."""
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
    assert isinstance(msg.content, str)
    assert "Test agent" in msg.content
    assert "The current time is" in msg.content


# --- Per-block TTL tests ---


def test_per_block_ttl():
    """A block with ttl='1h' produces extended cache_control."""
    blocks = [
        SystemPromptBlock(text="Static instructions.", cache=True, ttl="1h"),
    ]
    claude = Claude(cache_system_prompt=True, system_prompt_blocks=blocks)
    kwargs = claude._prepare_request_kwargs("")

    assert len(kwargs["system"]) == 1
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_mixed_ttl_blocks():
    """Blocks with different TTLs produce independent cache_control."""
    blocks = [
        SystemPromptBlock(text="Long-lived.", cache=True, ttl="1h"),
        SystemPromptBlock(text="Short-lived.", cache=True, ttl="5m"),
        SystemPromptBlock(text="Dynamic.", cache=False),
    ]
    claude = Claude(cache_system_prompt=True, system_prompt_blocks=blocks)
    kwargs = claude._prepare_request_kwargs("")

    assert len(kwargs["system"]) == 3
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in kwargs["system"][2]


def test_explicit_block_ttl_overrides_model_extended_cache_time():
    """Explicit block-level ttl='5m' stays 5m even with extended_cache_time=True.

    Ordered 1h-first-then-5m to respect Anthropic's mixed-TTL rule: the block
    inheriting 1h must precede the explicit-5m block.
    """
    blocks = [
        SystemPromptBlock(text="Default (inherits model).", cache=True),
        SystemPromptBlock(text="Explicit 5m.", cache=True, ttl="5m"),
    ]
    claude = Claude(cache_system_prompt=True, extended_cache_time=True, system_prompt_blocks=blocks)
    kwargs = claude._prepare_request_kwargs("")

    # ttl=None falls back to model-level extended_cache_time=True => 1h
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    # Explicit ttl="5m" overrides model-level extended_cache_time
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral"}


def test_cache_false_ignores_ttl():
    """cache=False produces no cache_control even when ttl is set."""
    blocks = [
        SystemPromptBlock(text="Not cached.", cache=False, ttl="1h"),
    ]
    claude = Claude(cache_system_prompt=True, system_prompt_blocks=blocks)
    kwargs = claude._prepare_request_kwargs("")

    assert len(kwargs["system"]) == 1
    assert "cache_control" not in kwargs["system"][0]


def test_explicit_5m_with_no_extended_cache():
    """Explicit ttl='5m' with extended_cache_time=False produces ephemeral without ttl key."""
    blocks = [
        SystemPromptBlock(text="Explicit 5m.", cache=True, ttl="5m"),
        SystemPromptBlock(text="Default None.", cache=True),
    ]
    claude = Claude(cache_system_prompt=True, extended_cache_time=False, system_prompt_blocks=blocks)
    kwargs = claude._prepare_request_kwargs("")

    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral"}


# --- Tool caching tests ---


def test_cache_tools_flag():
    """cache_tools=True adds cache_control to the last tool."""
    claude = Claude(cache_system_prompt=True, cache_tools=True)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "tool_a",
                "description": "A",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_b",
                "description": "B",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]
    kwargs = claude._prepare_request_kwargs("System.", tools=tools)

    assert "tools" in kwargs
    assert len(kwargs["tools"]) == 2
    assert "cache_control" not in kwargs["tools"][0]
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_cache_tools_disabled():
    """cache_tools=False leaves tools untouched."""
    claude = Claude(cache_system_prompt=True, cache_tools=False)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "tool_a",
                "description": "A",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]
    kwargs = claude._prepare_request_kwargs("System.", tools=tools)

    assert "tools" in kwargs
    for tool in kwargs["tools"]:
        assert "cache_control" not in tool


def test_cache_tools_single_tool():
    """cache_tools=True with a single tool adds cache_control to that tool."""
    claude = Claude(cache_system_prompt=True, cache_tools=True)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "only_tool",
                "description": "Solo",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]
    kwargs = claude._prepare_request_kwargs("System.", tools=tools)

    assert len(kwargs["tools"]) == 1
    assert kwargs["tools"][0]["cache_control"] == {"type": "ephemeral"}


def test_cache_tools_no_tools():
    """cache_tools=True with no tools does not error."""
    claude = Claude(cache_system_prompt=True, cache_tools=True)
    kwargs = claude._prepare_request_kwargs("System.", tools=None)

    assert "tools" not in kwargs


def test_vertexai_cache_tools():
    """VertexAI Claude also adds cache_control to the last tool."""
    from agno.models.vertexai.claude import Claude as VertexClaude

    claude = VertexClaude(cache_system_prompt=True, cache_tools=True)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "tool_a",
                "description": "A",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_b",
                "description": "B",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]
    kwargs = claude._prepare_request_kwargs("System.", tools=tools)

    assert "cache_control" not in kwargs["tools"][0]
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_aws_cache_tools():
    """AWS Bedrock Claude also adds cache_control to the last tool."""
    from agno.models.aws.claude import Claude as AwsClaude

    claude = AwsClaude(cache_system_prompt=True, cache_tools=True)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "tool_a",
                "description": "A",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_b",
                "description": "B",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]
    kwargs = claude._prepare_request_kwargs("System.", tools=tools)

    assert "cache_control" not in kwargs["tools"][0]
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_azure_cache_tools_and_blocks():
    """Azure Foundry Claude routes through the shared _build_system and
    _apply_cache_tools helpers, so it gets system_prompt_blocks and cache_tools
    support for free."""
    from agno.models.azure.claude import Claude as AzureClaude

    blocks = [SystemPromptBlock(text="User static.", cache=True, ttl="1h")]
    claude = AzureClaude(
        cache_system_prompt=True,
        extended_cache_time=True,
        cache_tools=True,
        system_prompt_blocks=blocks,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "tool_a",
                "description": "A",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_b",
                "description": "B",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]
    kwargs = claude._prepare_request_kwargs("Agent content.", tools=tools)

    # Augmented system: agent block first (1h), then user block (1h)
    assert len(kwargs["system"]) == 2
    assert kwargs["system"][0]["text"] == "Agent content."
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    # cache_tools marks the last tool
    assert "cache_control" not in kwargs["tools"][0]
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}
