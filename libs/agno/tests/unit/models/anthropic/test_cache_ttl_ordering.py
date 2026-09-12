"""Unit tests for Anthropic cache_control TTL ordering across tools + system.

Regression for: ``cache_tools=True`` together with ``extended_cache_time=True``
produced a 5m tools cache breakpoint followed by a 1h system breakpoint. Anthropic
renders cache breakpoints in ``tools`` -> ``system`` -> ``messages`` order and
rejects a request where a longer-TTL block follows a shorter-TTL one, so every
request 400'd. The fix makes the tools breakpoint honor ``extended_cache_time`` and
validates the combined tools+system breakpoint order at assembly time.
"""

import pytest

pytest.importorskip("anthropic")

from agno.models.anthropic.claude import Claude as AnthropicClaude
from agno.utils.models.claude import _validate_cache_ttl_order

_TOOL = {"name": "noop", "description": "no-op", "input_schema": {"type": "object", "properties": {}}}


def _breakpoints(request_kwargs):
    """cache_control dicts in Anthropic render order: tools -> system -> messages."""
    seq = [t["cache_control"] for t in request_kwargs.get("tools", []) if "cache_control" in t]
    seq += [b["cache_control"] for b in request_kwargs.get("system", []) if "cache_control" in b]
    return seq


def _ttl(cc):
    return cc.get("ttl", "5m")  # ephemeral with no ttl key == 5m default


def _is_valid_order(ttls):
    """Anthropic rule: a 1h breakpoint must not follow a 5m one in render order."""
    seen_5m = False
    for t in ttls:
        if t == "1h" and seen_5m:
            return False
        if t == "5m":
            seen_5m = True
    return True


def _anthropic_kwargs(**flags):
    model = AnthropicClaude(id="claude-sonnet-4-6", **flags)
    return model._prepare_request_kwargs(system_message="You are a helpful assistant.", tools=[dict(_TOOL)])


# ---------------------------------------------------------------------------
# Assembled-request behavior (AnthropicClaude)
# ---------------------------------------------------------------------------


def test_tools_ttl_matches_system_when_extended_cache_time():
    """The reported failing combo must now produce a valid, uniform 1h TTL."""
    seq = _breakpoints(_anthropic_kwargs(cache_tools=True, cache_system_prompt=True, extended_cache_time=True))
    assert len(seq) == 2  # one tools breakpoint + one system breakpoint
    assert all(cc == {"type": "ephemeral", "ttl": "1h"} for cc in seq)


def test_tools_default_to_5m_without_extended_cache_time():
    """Without extended_cache_time, tools stay at the default 5m (no ttl key)."""
    request_kwargs = _anthropic_kwargs(cache_tools=True, cache_system_prompt=True, extended_cache_time=False)
    assert request_kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.parametrize(
    "flags",
    [
        dict(cache_tools=True, cache_system_prompt=True, extended_cache_time=True),
        dict(cache_tools=True, cache_system_prompt=True, extended_cache_time=False),
        dict(cache_tools=True, cache_system_prompt=False, extended_cache_time=True),
    ],
)
def test_breakpoint_ttls_are_valid_order(flags):
    """No longer-TTL breakpoint may follow a shorter-TTL one in render order."""
    ttls = [_ttl(cc) for cc in _breakpoints(_anthropic_kwargs(**flags))]
    assert _is_valid_order(ttls), f"invalid TTL order {ttls} for {flags}"


# ---------------------------------------------------------------------------
# Validator (pure function, no model construction)
# ---------------------------------------------------------------------------


def test_validator_rejects_5m_tools_before_1h_system():
    """The exact cross-section case that previously shipped a 400 must raise locally."""
    with pytest.raises(ValueError, match="cache TTL ordering"):
        _validate_cache_ttl_order(
            [
                {"name": "noop", "cache_control": {"type": "ephemeral"}},  # tools 5m
                {"type": "text", "text": "x", "cache_control": {"type": "ephemeral", "ttl": "1h"}},  # system 1h
            ]
        )


def test_validator_allows_1h_tools_before_1h_system():
    _validate_cache_ttl_order(
        [
            {"name": "noop", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": "x", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        ]
    )


def test_validator_allows_5m_everywhere():
    _validate_cache_ttl_order(
        [
            {"name": "noop", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}},
        ]
    )


def test_validator_ignores_uncached_blocks():
    """Blocks without cache_control don't count as a 5m breakpoint."""
    _validate_cache_ttl_order(
        [
            {"name": "noop"},  # uncached tool
            {"type": "text", "text": "x", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        ]
    )


# ---------------------------------------------------------------------------
# Subclasses inherit the fix (shared base _apply_cache_tools)
# ---------------------------------------------------------------------------


def test_vertexai_tools_honor_extended_cache_time():
    from agno.models.vertexai.claude import Claude as VertexAIClaude

    model = VertexAIClaude(cache_tools=True, cache_system_prompt=True, extended_cache_time=True)
    request_kwargs = model._prepare_request_kwargs(system_message="You are a helpful assistant.", tools=[dict(_TOOL)])
    assert request_kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_aws_tools_honor_extended_cache_time():
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(cache_tools=True, cache_system_prompt=True, extended_cache_time=True)
    request_kwargs = model._prepare_request_kwargs(system_message="You are a helpful assistant.", tools=[dict(_TOOL)])
    assert request_kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
