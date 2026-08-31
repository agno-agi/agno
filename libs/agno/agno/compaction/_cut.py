"""Boundary and watermark selection: pair-safe, anchor-durable cut points.

All functions here are pure over an in-memory message list. Callers map chosen indices onto
stored-run coordinates.
"""

from typing import List, Optional

from agno.compaction._tokens import estimate_message_tokens
from agno.compaction.prompts import SUMMARY_PREFIX
from agno.models.message import Message

_LEADING_ROLES = ("system", "developer")


def leading_system_count(messages: List[Message]) -> int:
    """Number of leading system/developer messages — the block every view keeps verbatim."""
    count = 0
    for message in messages:
        if message.role in _LEADING_ROLES:
            count += 1
        else:
            break
    return count


def is_injected_compaction_message(message: Message) -> bool:
    """The summary/notice pair injected at view build. Never a boundary candidate, never counted
    as foldable: it is regenerated with fresh message ids each pass, so anchoring on it would fail
    permanently on the next build."""
    if not message.from_history or not isinstance(message.content, str):
        return False
    return message.content.startswith(SUMMARY_PREFIX)


def is_offload_envelope(message: Message) -> bool:
    """A stored-result envelope from offload_tool_results. Never elided or folded away: the
    result_id must survive verbatim so the model can read the payload back."""
    return message.role == "tool" and isinstance(message.content, str) and message.content.startswith('<result id="')


def keep_tail_start(messages: List[Message], keep_tokens: int, *, start: int = 0) -> int:
    """Index of the first message of a kept tail of ~keep_tokens, walking backward from the end.

    Injected summary/notice messages are not counted (they are regenerated per view, not kept
    content). Returns start when the whole span fits.
    """
    accumulated = 0
    index = len(messages)
    while index > start:
        candidate = messages[index - 1]
        if not is_injected_compaction_message(candidate):
            accumulated += estimate_message_tokens(candidate)
            if accumulated > keep_tokens:
                break
        index -= 1
    return index


def _owning_batch_head(messages: List[Message], index: int) -> Optional[int]:
    """For a tool-role message, the index of the assistant message owning its tool_call_id."""
    tool_call_id = messages[index].tool_call_id
    if not tool_call_id:
        return None
    for assistant_index in range(index - 1, -1, -1):
        for tool_call in messages[assistant_index].tool_calls or []:
            call_id = tool_call.get("id") if isinstance(tool_call, dict) else getattr(tool_call, "id", None)
            if call_id == tool_call_id:
                return assistant_index
    return None


def _is_durable_anchor(message: Message, *, allow_tool_batch_heads: bool = True) -> bool:
    """Anchor durability: the boundary/watermark message must survive in the stored transcript.

    temporary messages are removed mid-run; add_to_agent_memory=False messages are never
    persisted; when tool messages are scrubbed from storage, the assistant batch heads that own
    them are deleted too and cannot anchor.
    """
    if message.temporary or not message.add_to_agent_memory:
        return False
    if is_injected_compaction_message(message):
        return False
    if not allow_tool_batch_heads and message.role == "assistant" and message.tool_calls:
        return False
    return True


def choose_boundary(
    messages: List[Message],
    keep_tokens: int,
    *,
    min_index: int = 0,
    allow_tool_batch_heads: bool = True,
) -> Optional[int]:
    """Choose the boundary: the index of the first message kept verbatim.

    The kept tail accumulates ~keep_tokens walking backward; the boundary then snaps toward
    min_index to a pair-safe, durable user/assistant message — a tool result never starts the
    tail, and an orphan-threatened tool batch moves whole into it. Returns None when no valid
    boundary exists at or after min_index (the pass must abort rather than cut unsafely).

    min_index enforces monotonicity against the previous record's resolved boundary, and — for
    in-run passes — keeps the cut inside the current run's own messages.
    """
    lead = leading_system_count(messages)
    floor_index = max(min_index, lead)
    candidate = keep_tail_start(messages, keep_tokens, start=floor_index)
    if candidate <= floor_index:
        return None
    # An oversized newest message can push the walk past the end; a tail of at least one message
    # always survives.
    candidate = min(candidate, len(messages) - 1)

    index = candidate
    while index > floor_index:
        message = messages[index]
        if message.role == "tool":
            # Move the whole batch into the kept tail.
            head = _owning_batch_head(messages, index)
            index = head if head is not None and head >= floor_index else index - 1
            continue
        if message.role in _LEADING_ROLES or not _is_durable_anchor(
            message, allow_tool_batch_heads=allow_tool_batch_heads
        ):
            index -= 1
            continue
        # A tool result anywhere in the kept tail whose owning assistant falls before the
        # boundary would be orphaned; move the boundary to that batch head instead.
        orphan_head = _earliest_orphan_head(messages, index)
        if orphan_head is not None:
            index = orphan_head
            continue
        return index
    return None


def _earliest_orphan_head(messages: List[Message], boundary: int) -> Optional[int]:
    """The earliest batch head before boundary owning a tool message in messages[boundary:], or
    None when the tail is pair-safe. Tool messages with no recorded head are ignored — the
    canonical list itself carries that defect and a view must not be held to a higher bar."""
    earliest: Optional[int] = None
    for index in range(boundary, len(messages)):
        if messages[index].role != "tool":
            continue
        head = _owning_batch_head(messages, index)
        if head is not None and head < boundary and (earliest is None or head < earliest):
            earliest = head
    return earliest


def choose_watermark(
    messages: List[Message],
    tail_start: int,
    *,
    min_index: int = 0,
) -> Optional[str]:
    """Choose the elision watermark: the id of the first message kept un-elided.

    Scans from tail_start toward min_index for a durable message, so the watermark never
    advances into the kept tail; an undurable stretch degrades to less elision, never more.
    """
    index = min(tail_start, len(messages) - 1)
    while index >= min_index:
        message = messages[index]
        if message.role not in _LEADING_ROLES and _is_durable_anchor(message):
            return message.id
        index -= 1
    return None
