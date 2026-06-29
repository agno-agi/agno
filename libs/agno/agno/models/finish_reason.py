"""Normalized, cross-provider finish reasons.

Every provider reports why a generation stopped, but each uses a different name and value
set (Anthropic ``stop_reason``, OpenAI ``finish_reason``, Gemini ``finishReason``). Agno
previously inspected that value only to detect tool calls and discarded every other case,
so a truncated answer looked exactly like a clean one. This module normalizes the raw
provider value into a single :class:`FinishReason` enum while preserving the verbatim
provider string, so callers can reason about truncation, content filtering, tool calls,
etc. consistently across providers.

Design rules:

- Normalize to a str-backed enum AND keep the raw provider string (returned alongside).
- Never crash on an unseen value: every lookup falls back to ``FinishReason.UNKNOWN``.
- Unknown maps to ``UNKNOWN``, never to ``STOP`` (avoid silently reporting a clean
  completion for a generation that was actually truncated, filtered, or errored).

This module must stay import-clean: it imports nothing from agno except ``agno.utils.log``,
so it creates no import cycle with ``models/response.py``, ``run/agent.py``, or the providers.
"""

from enum import Enum
from typing import Any, Optional, Tuple

from agno.utils.log import log_warning


class FinishReason(str, Enum):
    """Normalized reason a model stopped generating.

    str-backed so it serializes for free and compares equal to its string value
    (``FinishReason.LENGTH == "length"``), keeping the field backward compatible.
    """

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALL = "tool_call"
    CONTENT_FILTER = "content_filter"
    PAUSE = "pause"
    REFUSAL = "refusal"
    ERROR = "error"
    UNKNOWN = "unknown"


def _key(value: Any) -> str:
    """Derive a stable string lookup key from a raw provider value.

    Provider values may be plain strings or SDK enum members. ``str(member)`` can render
    e.g. ``"FinishReason.MAX_TOKENS"`` for a str-backed SDK enum, so key off ``.name`` first
    and fall back to ``str()``. This is what keeps the live ``google.genai`` enum members
    (which are enum instances, not plain strings) from silently missing every map entry.
    """
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


# Anthropic Messages API stop reasons (direct + AWS Bedrock via AnthropicBedrock + Vertex + Azure).
_ANTHROPIC_MAP = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "max_tokens": FinishReason.LENGTH,
    "model_context_window_exceeded": FinishReason.LENGTH,
    "compaction": FinishReason.LENGTH,
    "tool_use": FinishReason.TOOL_CALL,
    "pause_turn": FinishReason.PAUSE,
    "refusal": FinishReason.REFUSAL,
}

# OpenAI Chat Completions finish reasons (covers the OpenAILike family + Groq + Cerebras).
_OPENAI_MAP = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "tool_calls": FinishReason.TOOL_CALL,
    "function_call": FinishReason.TOOL_CALL,
    "content_filter": FinishReason.CONTENT_FILTER,
}

# OpenAI Responses API: incomplete_details.reason values when status == "incomplete".
_OPENAI_RESPONSES_INCOMPLETE_MAP = {
    "max_output_tokens": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}

# Gemini (google.genai) finish reasons. Keyed by the enum member name (see _key).
_GEMINI_MAP = {
    "STOP": FinishReason.STOP,
    "MAX_TOKENS": FinishReason.LENGTH,
    "SAFETY": FinishReason.CONTENT_FILTER,
    "RECITATION": FinishReason.CONTENT_FILTER,
    "BLOCKLIST": FinishReason.CONTENT_FILTER,
    "PROHIBITED_CONTENT": FinishReason.CONTENT_FILTER,
    "SPII": FinishReason.CONTENT_FILTER,
    "LANGUAGE": FinishReason.CONTENT_FILTER,
    "IMAGE_SAFETY": FinishReason.CONTENT_FILTER,
    "MALFORMED_FUNCTION_CALL": FinishReason.ERROR,
    # OTHER, FINISH_REASON_UNSPECIFIED -> UNKNOWN via fallback.
}

# Bedrock Converse API stop reasons. Kept here for a future aws/bedrock.py (class AwsBedrock)
# wiring; the Anthropic Claude path (aws/claude.py) returns Anthropic-style stop_reason strings
# handled by _ANTHROPIC_MAP, not these Converse strings.
_BEDROCK_MAP = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "max_tokens": FinishReason.LENGTH,
    "tool_use": FinishReason.TOOL_CALL,
    "guardrail_intervened": FinishReason.CONTENT_FILTER,
    "content_filtered": FinishReason.CONTENT_FILTER,
}


def map_anthropic_finish_reason(value: Any) -> Tuple[FinishReason, str]:
    """Map an Anthropic ``stop_reason`` to a normalized reason and its raw key."""
    key = _key(value)
    return _ANTHROPIC_MAP.get(key, FinishReason.UNKNOWN), key


def map_openai_finish_reason(value: Any) -> Tuple[FinishReason, str]:
    """Map an OpenAI Chat Completions ``finish_reason`` to a normalized reason and its raw key."""
    key = _key(value)
    return _OPENAI_MAP.get(key, FinishReason.UNKNOWN), key


def map_openai_responses_finish_reason(status: Any, incomplete_reason: Any = None) -> Tuple[FinishReason, str]:
    """Map an OpenAI Responses API ``status`` (+ ``incomplete_details.reason``) to a normalized reason.

    ``status == "incomplete"`` carries the real reason in ``incomplete_details.reason``
    (``max_output_tokens`` -> LENGTH, ``content_filter`` -> CONTENT_FILTER). A ``completed``
    status is a normal stop. ``failed`` / ``cancelled`` are raised upstream as errors before
    parsing, so they are not mapped here.
    """
    status_key = _key(status)
    if status_key == "incomplete":
        reason_key = _key(incomplete_reason) if incomplete_reason is not None else "incomplete"
        return _OPENAI_RESPONSES_INCOMPLETE_MAP.get(reason_key, FinishReason.UNKNOWN), reason_key
    if status_key == "completed":
        return FinishReason.STOP, status_key
    return FinishReason.UNKNOWN, status_key


def map_gemini_finish_reason(value: Any) -> Tuple[FinishReason, str]:
    """Map a Gemini ``finish_reason`` (string or ``google.genai`` enum member) to a normalized reason."""
    key = _key(value)
    return _GEMINI_MAP.get(key, FinishReason.UNKNOWN), key


def map_bedrock_finish_reason(value: Any) -> Tuple[FinishReason, str]:
    """Map a Bedrock Converse API ``stopReason`` to a normalized reason and its raw key."""
    key = _key(value)
    return _BEDROCK_MAP.get(key, FinishReason.UNKNOWN), key


# Groq and native Cerebras both expose an OpenAI-shaped ``finish_reason``, so they reuse the map.
map_groq_finish_reason = map_openai_finish_reason
map_cerebras_finish_reason = map_openai_finish_reason


# Transient attribute used to deduplicate the truncation warning within a single run. It is set
# on the RunOutput/TeamRunOutput instance and is intentionally not a dataclass field, so it never
# appears in to_dict()/asdict() output or serialization.
_TRUNCATION_WARNED_ATTR = "_finish_reason_length_warned"


def warn_if_truncated(run_response: Any, finish_reason: Optional[FinishReason]) -> None:
    """Emit one de-duplicated warning per run when output was cut off by the token cap.

    ``run_response`` is an Agno ``RunOutput`` / ``TeamRunOutput``. It is kept untyped to avoid
    importing the run package (which would create an import cycle). A multi-step tool loop can
    reach ``LENGTH`` on more than one step, so the warning is guarded by a transient flag on the
    run so it fires at most once.
    """
    if finish_reason != FinishReason.LENGTH:
        return
    if run_response is None or getattr(run_response, _TRUNCATION_WARNED_ATTR, False):
        return
    try:
        setattr(run_response, _TRUNCATION_WARNED_ATTR, True)
    except Exception:
        # If the run object rejects the attribute, fall back to warning each time rather than crashing.
        pass
    log_warning(
        "The model stopped because it reached the maximum output token limit (finish_reason=length). "
        "The response is likely truncated; increase max_tokens for a complete response."
    )
