"""Derived model views: what the provider receives when compaction is active.

A view is built per provider call from the canonical message list plus the active record, then
discarded — never stored, never appended to, never re-read. Canonical messages are untouched:
every transformation lands on a shallow copy with the changed attribute rebound.
"""

from typing import List, Optional

from agno.compaction._cut import is_injected_compaction_message, is_offload_envelope, leading_system_count
from agno.compaction.compaction import CompactionRecord
from agno.compaction.prompts import ELISION_PLACEHOLDER, SUMMARY_PREFIX
from agno.models.message import Message


def summary_message(record: CompactionRecord) -> Message:
    return Message(role="user", content=SUMMARY_PREFIX + (record.summary or ""), from_history=True)


def notice_message(record: CompactionRecord) -> Message:
    return Message(role="user", content=record.notice or "", from_history=True)


def _find_index(messages: List[Message], message_id: str, *, start: int = 0) -> Optional[int]:
    for index in range(start, len(messages)):
        if messages[index].id == message_id:
            return index
    return None


def build_view(
    messages: List[Message],
    record: Optional[CompactionRecord],
    *,
    elide_exclude_tools: Optional[List[str]] = None,
    strip_provider_chaining: bool = False,
) -> List[Message]:
    """Derive the provider payload for one call.

    Leading system/developer messages pass verbatim. When the record's boundary resolves in this
    list, the summary and notice are injected and everything before the boundary is omitted — a
    summary is never injected unless its cut applies, so an unresolvable boundary fails open to
    the list as given. Tool results behind the elision watermark render as placeholders on
    copies. With strip_provider_chaining, assistant copies drop provider_data so server-side
    response chaining cannot silently rebuild the full history behind the view's back.
    """
    lead = leading_system_count(messages)

    boundary_index: Optional[int] = None
    if record is not None and record.summary and record.first_kept_message_id:
        boundary_index = _find_index(messages, record.first_kept_message_id, start=lead)

    watermark_index: Optional[int] = None
    if record is not None and record.elision_watermark_message_id:
        watermark_index = _find_index(messages, record.elision_watermark_message_id, start=lead)

    view: List[Message] = list(messages[:lead])
    if boundary_index is not None and record is not None:
        view.append(summary_message(record))
        if record.notice:
            view.append(notice_message(record))
        body_start = boundary_index
    else:
        body_start = lead

    exclude = set(elide_exclude_tools or [])
    for index in range(body_start, len(messages)):
        message = messages[index]
        # When this build injects the pair itself, drop any previously injected pair so a summary
        # never appears twice in one view.
        if boundary_index is not None and is_injected_compaction_message(message):
            continue
        if (
            watermark_index is not None
            and index < watermark_index
            and message.role == "tool"
            and not is_offload_envelope(message)
            and (message.tool_name or "") not in exclude
        ):
            content = message.content if isinstance(message.content, str) else str(message.content or "")
            message = message.model_copy(update={"content": ELISION_PLACEHOLDER.format(n_chars=len(content))})
        elif strip_provider_chaining and message.role == "assistant" and message.provider_data is not None:
            message = message.model_copy(update={"provider_data": None})
        view.append(message)
    return view
