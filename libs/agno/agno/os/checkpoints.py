from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


def _preview_message_content(content: Any, max_length: int = 120) -> Optional[str]:
    if content is None:
        return None
    preview = content if isinstance(content, str) else str(content)
    preview = preview.replace("\n", " ").strip()
    if len(preview) <= max_length:
        return preview
    return f"{preview[: max_length - 1]}..."


def _checkpoint_entry(run_output: Any, message_index: int, reason: str) -> Dict[str, Any]:
    """Build a single checkpoint entry.

    ``checkpoint_id`` is intentionally left as ``None`` here — it gets
    assigned by :func:`list_run_checkpoints` after the full list is sorted,
    so the value reflects display order (Checkpoint 1, 2, 3, …) rather than
    the underlying message index.
    """
    messages = run_output.messages or []
    message = messages[message_index - 1] if 0 < message_index <= len(messages) else None
    checkpoint_status = getattr(message, "checkpoint_status", None) if message is not None else None
    checkpoint_created_at = getattr(message, "checkpoint_created_at", None) if message is not None else None
    run_status = getattr(run_output.status, "value", run_output.status)

    return {
        "checkpoint_id": None,  # filled in by list_run_checkpoints
        "run_id": run_output.run_id,
        "session_id": run_output.session_id,
        "message_index": message_index,
        "continue_from": message_index,
        "status": checkpoint_status or run_status,
        "reason": reason,
        "created_at": checkpoint_created_at or getattr(run_output, "created_at", None),
        "message_id": getattr(message, "id", None) if message is not None else None,
        "message_role": getattr(message, "role", None) if message is not None else None,
        "message_preview": _preview_message_content(getattr(message, "content", None)) if message is not None else None,
        "is_latest": message_index == len(messages),
    }


def list_run_checkpoints(run_output: Any) -> List[Dict[str, Any]]:
    """Return FE-friendly checkpoint boundaries derived from the current run row.

    Entries are inferred from message-level checkpoint markers and the terminal
    end of the current transcript — this intentionally does not introduce a
    separate persistence source.

    ``checkpoint_id`` is a 1-based display ordinal over the returned list
    (Checkpoint 1, 2, 3, …) so the FE can label pins sequentially. Use
    ``message_index`` (not ``checkpoint_id``) when calling back into
    ``/continue?continue_from=...`` — that's the value the dispatch understands.
    """
    messages = run_output.messages or []
    checkpoints_by_index: Dict[int, Dict[str, Any]] = {}

    last_checkpoint_index = getattr(run_output, "last_checkpoint_at_message_index", None)
    if isinstance(last_checkpoint_index, int) and 0 <= last_checkpoint_index <= len(messages):
        checkpoints_by_index[last_checkpoint_index] = _checkpoint_entry(
            run_output, last_checkpoint_index, reason="checkpoint"
        )

    for idx, message in enumerate(messages, start=1):
        if getattr(message, "checkpoint_status", None) is not None:
            checkpoints_by_index[idx] = _checkpoint_entry(run_output, idx, reason="checkpoint")

    if messages:
        checkpoints_by_index[len(messages)] = _checkpoint_entry(run_output, len(messages), reason="end")

    # Assign sequential display IDs in sorted order so the FE shows
    # "Checkpoint 1, 2, 3, …" instead of indices like "4, 6, 7" that look
    # arbitrary to a user.
    entries = [checkpoints_by_index[idx] for idx in sorted(checkpoints_by_index)]
    for ordinal, entry in enumerate(entries, start=1):
        entry["checkpoint_id"] = str(ordinal)
    return entries


def _referenced_tool_call_ids(messages: List[Any]) -> set:
    tool_call_ids = set()
    for message in messages:
        tool_call_id = getattr(message, "tool_call_id", None)
        if tool_call_id:
            tool_call_ids.add(tool_call_id)
        for tool_call in getattr(message, "tool_calls", None) or []:
            if isinstance(tool_call, dict):
                tool_call_id = tool_call.get("id")
            else:
                tool_call_id = getattr(tool_call, "id", None)
            if tool_call_id:
                tool_call_ids.add(tool_call_id)
    return tool_call_ids


def build_run_checkpoint_snapshot(run_output: Any, message_index: int) -> Dict[str, Any]:
    """Return a truncated run snapshot at ``message_index``.

    The returned payload is derived from a deep copy of the persisted run and
    never mutates the stored run object.
    """
    from agno.utils.message import safe_truncation_index

    messages = run_output.messages or []
    if message_index < 0 or message_index > len(messages):
        raise ValueError(f"message_index must be between 0 and {len(messages)}")

    # Snap down so the snapshot never ends with an orphaned tool_call.
    safe_index = safe_truncation_index(messages, message_index)

    snapshot = copy.deepcopy(run_output)
    snapshot.messages = list(snapshot.messages or [])[:safe_index]
    snapshot.last_checkpoint_at_message_index = safe_index

    valid_tool_call_ids = _referenced_tool_call_ids(snapshot.messages)
    if getattr(snapshot, "tools", None):
        snapshot.tools = [tool for tool in snapshot.tools if getattr(tool, "tool_call_id", None) in valid_tool_call_ids]
    if getattr(snapshot, "requirements", None):
        snapshot.requirements = [
            requirement
            for requirement in snapshot.requirements
            if getattr(getattr(requirement, "tool_execution", None), "tool_call_id", None) in valid_tool_call_ids
        ]

    # Match the display ordinal the FE would have seen on the timeline
    # (Checkpoint 1, 2, 3, …) so the snapshot's checkpoint_id is consistent
    # with GET /checkpoints. Falls back to None if the requested index isn't
    # a known checkpoint boundary on the run.
    entry = _checkpoint_entry(run_output, message_index, reason="snapshot")
    timeline = list_run_checkpoints(run_output)
    for known in timeline:
        if known.get("message_index") == message_index:
            entry["checkpoint_id"] = known.get("checkpoint_id")
            break

    return {
        "checkpoint": entry,
        "snapshot": snapshot.to_dict() if hasattr(snapshot, "to_dict") else snapshot,
    }
