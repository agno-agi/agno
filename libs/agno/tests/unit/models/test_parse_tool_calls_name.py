"""
Unit tests for parse_tool_calls function name deduplication across 6 providers.

Function names are atomic — sent complete in a single streaming chunk, not
fragmented across chunks the way arguments are. Using `+=` to accumulate them
produces duplication (e.g. "retrieve_contentsretrieve_contents") when the same
name appears in a subsequent chunk. The fix assigns (`=`) instead of appending.

Additionally, for LiteLLM (especially with Claude), empty strings in subsequent
chunks should not overwrite valid names (GitHub Issue #6757).

Covers: openai, groq, huggingface, cerebras, ibm/watsonx, litellm
Test cases per provider:
  1. Name sent once — normal path, name set correctly
  2. Name resent across chunks — no duplication (core regression)
  3. Arguments streamed incrementally — `+=` still works for arguments
  4. Multiple tool calls — independent names don't cross-contaminate
  5. Empty strings don't overwrite valid names (LiteLLM/Claude specific)
"""

from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


class _MockFunction:
    """Minimal mock for ChoiceDeltaToolCall.function (openai/groq shape)."""

    def __init__(self, name: Optional[str] = None, arguments: Optional[str] = None):
        self.name = name
        self.arguments = arguments


class _MockChoiceDeltaToolCall:
    """Minimal mock for openai.types.chat.chat_completion_chunk.ChoiceDeltaToolCall."""

    def __init__(
        self,
        index: int = 0,
        id: Optional[str] = None,
        type: Optional[str] = None,
        name: Optional[str] = None,
        arguments: Optional[str] = None,
    ):
        self.index = index
        self.id = id
        self.type = type
        self.function = _MockFunction(name=name, arguments=arguments)


class _MockHFFunction:
    """Minimal mock for huggingface ChatCompletionStreamOutputDeltaToolCall.function."""

    def __init__(self, name: Optional[str] = None, arguments: Optional[str] = None):
        self.name = name
        self.arguments = arguments


class _MockHFToolCall:
    """
    Minimal mock for huggingface ChatCompletionStreamOutputDeltaToolCall.

    HuggingFace's parse_tool_calls receives List[ChatCompletionStreamOutputDeltaToolCall]
    where each element is *itself* iterable/subscriptable — the code does tool_call[0]
    at line ~385, so each item in tool_calls_data must be a list wrapping the real object.
    """

    def __init__(
        self,
        index: int = 0,
        id: Optional[str] = None,
        type: Optional[str] = None,
        name: Optional[str] = None,
        arguments: Optional[str] = None,
    ):
        self.index = index
        self.id = id
        self.type = type
        self.function = _MockHFFunction(name=name, arguments=arguments)


def _hf_chunk(
    index: int = 0,
    id: Optional[str] = None,
    type: Optional[str] = None,
    name: Optional[str] = None,
    arguments: Optional[str] = None,
) -> List[_MockHFToolCall]:
    """Wrap a mock HF tool call in the list that parse_tool_calls expects as one element."""
    return [_MockHFToolCall(index=index, id=id, type=type, name=name, arguments=arguments)]


def _cerebras_chunk(
    index: int = 0,
    id: Optional[str] = None,
    type: Optional[str] = None,
    name: Optional[str] = None,
    arguments: Optional[str] = None,
) -> Dict[str, Any]:
    """Plain dict shape used by Cerebras and IBM/WatsonX parse_tool_calls."""
    chunk: Dict[str, Any] = {"index": index}
    if id is not None:
        chunk["id"] = id
    if type is not None:
        chunk["type"] = type
    func: Dict[str, Any] = {}
    if name is not None:
        func["name"] = name
    if arguments is not None:
        func["arguments"] = arguments
    if func:
        chunk["function"] = func
    return chunk


# WatsonX uses the same dict shape as Cerebras.
_watsonx_chunk = _cerebras_chunk


def _litellm_chunk(
    index: int = 0,
    id: Optional[str] = None,
    type: Optional[str] = None,
    name: Optional[str] = None,
    arguments: Optional[str] = None,
) -> Dict[str, Any]:
    """Plain dict shape used by LiteLLM parse_tool_calls."""
    chunk: Dict[str, Any] = {"index": index}
    if id is not None:
        chunk["id"] = id
    if type is not None:
        chunk["type"] = type
    func: Dict[str, Any] = {}
    if name is not None:
        func["name"] = name
    if arguments is not None:
        func["arguments"] = arguments
    if func:
        chunk["function"] = func
    return chunk


# ---------------------------------------------------------------------------
# Provider parse_tool_calls callables
# ---------------------------------------------------------------------------


def _openai_parse(chunks):
    from agno.models.openai.chat import OpenAIChat

    return OpenAIChat.parse_tool_calls(chunks)


def _groq_parse(chunks):
    from agno.models.groq.groq import Groq

    return Groq.parse_tool_calls(chunks)


def _huggingface_parse(chunks):
    from agno.models.huggingface.huggingface import HuggingFace

    return HuggingFace.parse_tool_calls(chunks)


def _cerebras_parse(chunks):
    # Cerebras.parse_tool_calls is an instance method (not @staticmethod)
    from agno.models.cerebras.cerebras import Cerebras

    model = Cerebras.__new__(Cerebras)
    return model.parse_tool_calls(chunks)


def _watsonx_parse(chunks):
    from agno.models.ibm.watsonx import WatsonX

    return WatsonX.parse_tool_calls(chunks)


def _litellm_parse(chunks):
    from agno.models.litellm.chat import LiteLLM

    return LiteLLM.parse_tool_calls(chunks)


# ---------------------------------------------------------------------------
# Parameterization helpers
# ---------------------------------------------------------------------------

# Each provider entry: (provider_id, parse_fn, chunk_factory, first_chunk_kwargs)
# first_chunk_kwargs must produce a valid "first chunk" that initialises the entry.

PROVIDERS = [
    "openai",
    "groq",
    "huggingface",
    "cerebras",
    "watsonx",
    # "litellm",  # Temporarily disabled - litellm compromised on PyPI (March 24, 2026)
]


def _make_chunks(provider: str, specs: List[Dict[str, Any]]) -> List[Any]:
    """
    Build a list of chunks for the given provider from a list of spec dicts.
    Each spec dict may have: index, id, type, name, arguments.
    """
    result = []
    for spec in specs:
        if provider in ("openai", "groq"):
            result.append(_MockChoiceDeltaToolCall(**spec))
        elif provider == "huggingface":
            result.append(_hf_chunk(**spec))
        elif provider == "cerebras":
            result.append(_cerebras_chunk(**spec))
        elif provider == "watsonx":
            result.append(_watsonx_chunk(**spec))
        elif provider == "litellm":
            result.append(_litellm_chunk(**spec))
        else:
            raise ValueError(f"Unknown provider: {provider}")
    return result


def _parse(provider: str, chunks: List[Any]) -> List[Dict[str, Any]]:
    dispatch = {
        "openai": _openai_parse,
        "groq": _groq_parse,
        "huggingface": _huggingface_parse,
        "cerebras": _cerebras_parse,
        "watsonx": _watsonx_parse,
        "litellm": _litellm_parse,
    }
    return dispatch[provider](chunks)


# ---------------------------------------------------------------------------
# Test 1: Name sent once — normal path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDERS)
def test_name_sent_once(provider: str) -> None:
    """When a function name arrives in a single chunk it must be set exactly."""
    chunks = _make_chunks(
        provider,
        [
            {"index": 0, "id": "call_1", "type": "function", "name": "get_weather", "arguments": ""},
        ],
    )
    result = _parse(provider, chunks)
    assert len(result) >= 1
    assert result[0]["function"]["name"] == "get_weather"


# ---------------------------------------------------------------------------
# Test 2: Name resent across chunks — no duplication (core regression)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDERS)
def test_name_not_duplicated_when_resent(provider: str) -> None:
    """
    When the same function name appears in a subsequent chunk (provider resends it),
    the result must NOT concatenate: 'get_weatherget_weather' is wrong.
    """
    chunks = _make_chunks(
        provider,
        [
            # First chunk: initialises the entry
            {"index": 0, "id": "call_1", "type": "function", "name": "get_weather", "arguments": ""},
            # Second chunk: provider resends the name (plus more arguments)
            {"index": 0, "name": "get_weather", "arguments": '{"city":'},
        ],
    )
    result = _parse(provider, chunks)
    assert len(result) >= 1
    assert result[0]["function"]["name"] == "get_weather", (
        f"[{provider}] Expected 'get_weather' but got '{result[0]['function']['name']}' — "
        "name was duplicated via += instead of ="
    )


# ---------------------------------------------------------------------------
# Test 3: Arguments streamed incrementally — += still works
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDERS)
def test_arguments_accumulated_incrementally(provider: str) -> None:
    """Arguments arrive in fragments and must be concatenated, not replaced."""
    chunks = _make_chunks(
        provider,
        [
            {"index": 0, "id": "call_1", "type": "function", "name": "search", "arguments": '{"q":'},
            {"index": 0, "arguments": '"python"}'},
        ],
    )
    result = _parse(provider, chunks)
    assert len(result) >= 1
    assert result[0]["function"]["arguments"] == '{"q":"python"}', (
        f"[{provider}] Arguments not accumulated correctly: '{result[0]['function']['arguments']}'"
    )


# ---------------------------------------------------------------------------
# Test 4: Multiple tool calls — names don't cross-contaminate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDERS)
def test_multiple_tool_calls_independent(provider: str) -> None:
    """Two parallel tool calls at index 0 and 1 must not share names."""
    chunks = _make_chunks(
        provider,
        [
            # Tool call 0
            {"index": 0, "id": "call_0", "type": "function", "name": "get_weather", "arguments": '{"city":'},
            # Tool call 1
            {"index": 1, "id": "call_1", "type": "function", "name": "search_web", "arguments": '{"q":'},
            # Argument continuation for tool call 0
            {"index": 0, "arguments": '"Paris"}'},
            # Argument continuation for tool call 1
            {"index": 1, "arguments": '"agno"}'},
        ],
    )
    result = _parse(provider, chunks)
    assert len(result) >= 2, f"[{provider}] Expected 2 tool calls, got {len(result)}"

    names = {tc["function"]["name"] for tc in result}
    assert "get_weather" in names, f"[{provider}] 'get_weather' missing from results: {result}"
    assert "search_web" in names, f"[{provider}] 'search_web' missing from results: {result}"

    # Verify arguments didn't cross
    tc0 = next(tc for tc in result if tc["function"]["name"] == "get_weather")
    tc1 = next(tc for tc in result if tc["function"]["name"] == "search_web")
    assert tc0["function"]["arguments"] == '{"city":"Paris"}', (
        f"[{provider}] tc0 args wrong: '{tc0['function']['arguments']}'"
    )
    assert tc1["function"]["arguments"] == '{"q":"agno"}', (
        f"[{provider}] tc1 args wrong: '{tc1['function']['arguments']}'"
    )


# ---------------------------------------------------------------------------
# Test 5: Empty strings don't overwrite valid names (GitHub Issue #6757)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDERS)
def test_empty_string_does_not_overwrite_name(provider: str) -> None:
    """
    When an empty string name appears in a subsequent chunk (common with Claude
    via LiteLLM streaming), the valid name must NOT be overwritten.

    - Chunk 1: name="add" (valid)
    - Chunk 2: name="" (empty string, should be ignored)
    - Result should have name="add", not name=""
    """
    chunks = _make_chunks(
        provider,
        [
            # First chunk: valid name, empty arguments
            {"index": 0, "id": "call_1", "type": "function", "name": "get_weather", "arguments": ""},
            # Second chunk: empty name (should be ignored), arguments start streaming
            {"index": 0, "name": "", "arguments": '{"city":'},
            # Third chunk: empty name again, arguments continue
            {"index": 0, "name": "", "arguments": '"Paris"}'},
        ],
    )
    result = _parse(provider, chunks)
    assert len(result) >= 1, f"[{provider}] Expected at least 1 tool call, got {len(result)}"
    assert result[0]["function"]["name"] == "get_weather", (
        f"[{provider}] Expected 'get_weather' but got '{result[0]['function']['name']}'. "
        "When streaming tool calls, the name is sent in the first chunk and subsequent chunks "
        "may contain empty string names. The condition `if name is not None` incorrectly treats "
        "empty strings as valid, overwriting the real name. Fix: use `if name:` (truthiness check) "
        "to skip empty strings."
    )
    assert result[0]["function"]["arguments"] == '{"city":"Paris"}', (
        f"[{provider}] Arguments not accumulated correctly: '{result[0]['function']['arguments']}'"
    )
