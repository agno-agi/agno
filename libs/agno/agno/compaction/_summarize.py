"""The summariser fold: previous summary + rendered segment -> updated summary.

The segment is rendered to flat text before the model call. Rendering rather than replaying
messages is structural safety: a text payload can carry no provider response-chaining state and
no tool-call linkage for a provider to reject, whatever model the summariser is.
"""

from typing import TYPE_CHECKING, List, Optional

from agno.compaction._cut import is_injected_compaction_message, is_offload_envelope
from agno.compaction.prompts import DEFAULT_COMPACTION_PROMPT, UNTRUSTED_INSTRUCTIONS_WRAPPER
from agno.models.message import Message

if TYPE_CHECKING:
    from agno.metrics import RunMetrics
    from agno.models.base import Model

# Rendering cap per tool result (characters) — distinct from the token output budget.
_TOOL_RESULT_RENDER_CHARS = 2_000
# Fraction of the summariser's own window one fold call may fill; larger inputs fold in chunks.
_CHUNK_WINDOW_FRACTION = 0.5
_APPROX_CHARS_PER_TOKEN = 4


def render_segment(messages: List[Message]) -> str:
    """Flatten a message segment to labeled plain text."""
    parts: List[str] = []
    for message in messages:
        if message.role in ("system", "developer") or is_injected_compaction_message(message):
            continue
        content = message.content if isinstance(message.content, str) else str(message.content or "")
        if message.role == "assistant":
            header = "assistant"
            if message.tool_calls:
                names = []
                for tool_call in message.tool_calls:
                    function = tool_call.get("function") if isinstance(tool_call, dict) else None
                    name = function.get("name") if isinstance(function, dict) else None
                    names.append(name or "tool")
                header += " (called: " + ", ".join(names) + ")"
        elif message.role == "tool":
            header = f"tool result ({message.tool_name})" if message.tool_name else "tool result"
            # Offload envelopes render whole: the result_id must survive verbatim.
            if not is_offload_envelope(message) and len(content) > _TOOL_RESULT_RENDER_CHARS:
                content = content[:_TOOL_RESULT_RENDER_CHARS] + "\n... [tool result truncated]"
        else:
            header = message.role
        if not content and not (message.role == "assistant" and message.tool_calls):
            continue
        parts.append(f"[{header}]\n{content}")
    return "\n\n".join(parts)


def _build_prompt(
    budget_tokens: int,
    config_instructions: Optional[str],
    call_instructions: Optional[str],
) -> str:
    prompt = DEFAULT_COMPACTION_PROMPT.format(budget_tokens=budget_tokens)
    if config_instructions:
        prompt += (
            "\n\nStanding operator instructions for every summary (they add emphasis; the rules above "
            f"still apply in full):\n{config_instructions}"
        )
    if call_instructions:
        prompt += (
            "\n\nOperator focus for this pass. It takes precedence: detail the focused material fully, "
            f"and outside it prefer brevity over completeness:\n{call_instructions}"
        )
    return prompt


def _build_user_message(previous_summary: Optional[str], segment_text: str, untrusted_instructions: Optional[str]) -> str:
    parts: List[str] = []
    if previous_summary:
        parts.append(f"Previous summary:\n\n{previous_summary}")
    else:
        parts.append("There is no previous summary; this is the first fold.")
    parts.append(f"Transcript segment to fold in:\n\n<conversation>\n{segment_text}\n</conversation>")
    if untrusted_instructions:
        parts.append(UNTRUSTED_INSTRUCTIONS_WRAPPER.format(instructions=untrusted_instructions))
    parts.append("Produce the updated summary now.")
    return "\n\n".join(parts)


def _chunks(segment_text: str, summarizer_window: Optional[int]) -> List[str]:
    """Split an oversized rendered segment so the summariser never overflows itself."""
    window = summarizer_window or 200_000
    max_chars = int(window * _CHUNK_WINDOW_FRACTION) * _APPROX_CHARS_PER_TOKEN
    if len(segment_text) <= max_chars:
        return [segment_text]
    chunks: List[str] = []
    remaining = segment_text
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        split = remaining.rfind("\n\n", 0, max_chars)
        if split <= 0:
            split = max_chars
        chunks.append(remaining[:split])
        remaining = remaining[split:]
    return chunks


def fold(
    model: "Model",
    previous_summary: Optional[str],
    segment_text: str,
    *,
    budget_tokens: int,
    summarizer_window: Optional[int] = None,
    config_instructions: Optional[str] = None,
    call_instructions: Optional[str] = None,
    untrusted_instructions: Optional[str] = None,
    run_metrics: Optional["RunMetrics"] = None,
) -> str:
    """One fold. Exceptions propagate; the caller owns the fail-open contract."""
    system_prompt = _build_prompt(budget_tokens, config_instructions, call_instructions)
    summary = previous_summary
    for chunk in _chunks(segment_text, summarizer_window):
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=_build_user_message(summary, chunk, untrusted_instructions)),
        ]
        response = model.response(messages=messages)
        _accumulate(response, model, run_metrics)
        summary = (response.content or "").strip()
    return summary or ""


async def afold(
    model: "Model",
    previous_summary: Optional[str],
    segment_text: str,
    *,
    budget_tokens: int,
    summarizer_window: Optional[int] = None,
    config_instructions: Optional[str] = None,
    call_instructions: Optional[str] = None,
    untrusted_instructions: Optional[str] = None,
    run_metrics: Optional["RunMetrics"] = None,
) -> str:
    """Async twin of fold."""
    system_prompt = _build_prompt(budget_tokens, config_instructions, call_instructions)
    summary = previous_summary
    for chunk in _chunks(segment_text, summarizer_window):
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=_build_user_message(summary, chunk, untrusted_instructions)),
        ]
        response = await model.aresponse(messages=messages)
        _accumulate(response, model, run_metrics)
        summary = (response.content or "").strip()
    return summary or ""


def _accumulate(response, model: "Model", run_metrics: Optional["RunMetrics"]) -> None:
    if run_metrics is None:
        return
    from agno.metrics import ModelType, accumulate_model_metrics

    accumulate_model_metrics(response, model, ModelType.COMPACTION_MODEL, run_metrics)
