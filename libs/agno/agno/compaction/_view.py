"""Derived model views: what the provider receives when compaction is active.

A view is built per provider call from the canonical message list plus the active record, then
discarded — never stored, never appended to, never re-read. Canonical messages are untouched:
every transformation lands on a shallow copy with the changed attribute rebound.
"""

import re
from typing import List, Optional

from agno.compaction._cut import is_injected_compaction_message, is_offload_envelope, leading_system_count
from agno.compaction.prompts import ELISION_PLACEHOLDER, SUMMARY_PREFIX
from agno.compaction.types import CompactionRecord
from agno.models.message import Message

_RESULT_ID_PATTERN = re.compile(r'<result id="([^"]+)"')
_MAX_SURVIVING_IDS = 100


def surviving_result_ids(folded: List[Message]) -> List[str]:
    """Result ids from offload envelopes that this fold is about to remove.

    An envelope's id is the only handle the model has on a stored payload, so folding one away
    silently orphans it. Pinning envelopes in the kept tail was the other option, but a single
    early envelope then caps the boundary forever and compaction stops working entirely. Carrying
    the ids forward keeps the payloads reachable at a bounded, constant cost.
    """
    ids: List[str] = []
    for message in folded:
        if not is_offload_envelope(message):
            continue
        content = message.content if isinstance(message.content, str) else ""
        match = _RESULT_ID_PATTERN.search(content)
        if match and match.group(1) not in ids:
            ids.append(match.group(1))
        if len(ids) >= _MAX_SURVIVING_IDS:
            break
    return ids


def summary_message(
    record: CompactionRecord, suffix: Optional[str] = None, result_ids: Optional[List[str]] = None
) -> Message:
    content = SUMMARY_PREFIX + (record.summary or "")
    if result_ids:
        content += (
            "\n\nStored tool results from the folded conversation remain readable with "
            f"read_result(id): {', '.join(result_ids)}"
        )
    if suffix:
        content += suffix
    return Message(role="user", content=content, from_history=True)


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
    summary_suffix: Optional[str] = None,
) -> List[Message]:
    """Derive the provider payload for one call.

    Leading system/developer messages pass verbatim. When the record's boundary resolves in this
    list, the summary is injected and everything before the boundary is omitted — a
    summary is never injected unless its cut applies, so an unresolvable boundary fails open to
    the list as given. Tool results behind the elision watermark render as placeholders on
    copies. With strip_provider_chaining, assistant copies drop the response-chaining key from
    provider_data (reasoning items and other payload survive: a function_call without its paired
    reasoning item is a provider error) so server-side chaining cannot silently rebuild the full
    history behind the view's back.
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
        view.append(summary_message(record, summary_suffix, surviving_result_ids(messages[lead:boundary_index])))
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
        elif (
            strip_provider_chaining
            and message.role == "assistant"
            and message.provider_data is not None
            and "response_id" in message.provider_data
        ):
            trimmed = {key: value for key, value in message.provider_data.items() if key != "response_id"}
            message = message.model_copy(update={"provider_data": trimmed or None})
        view.append(message)
    return view
