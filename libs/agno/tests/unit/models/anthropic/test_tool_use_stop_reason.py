"""Claude must extract tool_use blocks regardless of stop_reason.

A complete tool_use block can be returned with a stop_reason other than
"tool_use" (e.g. "pause_turn" for long-running server-tool turns, or "max_tokens"
after a complete tool_use block). The non-streaming parser previously gated tool
extraction on ``stop_reason == "tool_use"``, so those tool calls were silently
dropped and the requested tool never ran — unlike the streaming path and every
OpenAI-compatible model, which extract tool calls independent of the stop reason.
"""

from types import SimpleNamespace

import pytest

from agno.models.anthropic.claude import Claude


def _response(stop_reason: str) -> SimpleNamespace:
    tool_block = SimpleNamespace(type="tool_use", id="toolu_1", name="get_weather", input={"city": "SF"})
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        server_tool_use=None,
    )
    return SimpleNamespace(role="assistant", content=[tool_block], stop_reason=stop_reason, usage=usage)


@pytest.mark.parametrize("stop_reason", ["tool_use", "max_tokens", "pause_turn"])
def test_tool_use_extracted_regardless_of_stop_reason(stop_reason):
    model = Claude(id="claude-sonnet-4-5")

    result = model._parse_provider_response(_response(stop_reason))

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["id"] == "toolu_1"
    assert result.tool_calls[0]["function"]["name"] == "get_weather"
