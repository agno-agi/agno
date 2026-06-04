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
    messages = run_output.messages or []
    message = messages[message_index - 1] if 0 < message_index <= len(messages) else None
    checkpoint_status = getattr(message, "checkpoint_status", None) if message is not None else None
    checkpoint_created_at = getattr(message, "checkpoint_created_at", None) if message is not None else None
    run_status = getattr(run_output.status, "value", run_output.status)

    return {
        "checkpoint_id": str(message_index),
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

    This intentionally does not create another persistence source. Checkpoints
    are inferred from message-level checkpoint markers and the terminal end of
    the current transcript.
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

    return [checkpoints_by_index[idx] for idx in sorted(checkpoints_by_index)]


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
    messages = run_output.messages or []
    if message_index < 0 or message_index > len(messages):
        raise ValueError(f"message_index must be between 0 and {len(messages)}")

    snapshot = copy.deepcopy(run_output)
    snapshot.messages = list(snapshot.messages or [])[:message_index]
    snapshot.last_checkpoint_at_message_index = message_index

    valid_tool_call_ids = _referenced_tool_call_ids(snapshot.messages)
    if getattr(snapshot, "tools", None):
        snapshot.tools = [tool for tool in snapshot.tools if getattr(tool, "tool_call_id", None) in valid_tool_call_ids]
    if getattr(snapshot, "requirements", None):
        snapshot.requirements = [
            requirement
            for requirement in snapshot.requirements
            if getattr(getattr(requirement, "tool_execution", None), "tool_call_id", None) in valid_tool_call_ids
        ]

    return {
        "checkpoint": _checkpoint_entry(run_output, message_index, reason="snapshot"),
        "snapshot": snapshot.to_dict() if hasattr(snapshot, "to_dict") else snapshot,
    }
