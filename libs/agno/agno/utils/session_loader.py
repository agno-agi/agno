"""Utilities for reconstructing session messages that include tool calls."""

from __future__ import annotations

from typing import Any, Dict, List

from agno.models.message import Message
from agno.utils.log import log_debug, log_warning


def _create_synthetic_tool_result_message(tool_call_id: str, function_name: str) -> Message:
    """Return a placeholder tool result when the persisted run is missing one."""

    return Message(
        role="tool",
        tool_call_id=tool_call_id,
        tool_name=function_name,
        tool_call_error=True,
        content=(
            "Tool execution result was not persisted in the session history. "
            f"The {function_name} tool likely completed, but its output is unavailable."
        ),
    )


def ensure_message_continuity(messages: List[Message]) -> List[Message]:
    """Ensure that every tool call is immediately followed by a tool result.

    This mirrors the ordering requirements enforced by Anthropic's Claude API and prevents
    historical transcripts from violating the `tool_use` → `tool_result` contract.
    """

    if not messages:
        return messages

    fixed_messages: List[Message] = []
    i = 0

    while i < len(messages):
        message = messages[i]

        if message.role == "assistant" and message.tool_calls:
            fixed_messages.append(message)

            tool_call_id_to_name: Dict[str, str] = {}
            ordered_tool_call_ids: List[str] = []

            for tool_call in message.tool_calls:
                tool_call_id = tool_call.get("id")
                if not tool_call_id:
                    continue

                ordered_tool_call_ids.append(tool_call_id)
                function_name = "unknown"
                function_def = tool_call.get("function")
                if isinstance(function_def, dict):
                    function_name = function_def.get("name") or "unknown"

                tool_call_id_to_name[tool_call_id] = function_name

            j = i + 1
            while (
                j < len(messages)
                and messages[j].role == "tool"
                and messages[j].tool_call_id in tool_call_id_to_name
            ):
                tool_msg = messages[j]
                if tool_msg.tool_call_id in ordered_tool_call_ids:
                    ordered_tool_call_ids.remove(tool_msg.tool_call_id)
                fixed_messages.append(tool_msg)
                j += 1

            if ordered_tool_call_ids:
                log_warning(
                    "Missing tool results detected for tool_call_ids: %s",
                    ordered_tool_call_ids,
                )
                for missing_id in ordered_tool_call_ids:
                    synthetic_result = _create_synthetic_tool_result_message(
                        missing_id, tool_call_id_to_name.get(missing_id, "unknown")
                    )
                    fixed_messages.append(synthetic_result)
                    log_debug("Created synthetic tool result for tool_call_id=%s", missing_id)

            i = j
            continue

        if message.role == "tool":
            if not message.tool_call_id:
                log_warning("Skipping tool result without tool_call_id in session history")
            else:
                log_warning(
                    "Skipping orphaned tool result tool_call_id=%s because no matching assistant call was found",
                    message.tool_call_id,
                )
            i += 1
            continue

        fixed_messages.append(message)
        i += 1

    return fixed_messages


def ensure_message_dict_continuity(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dictionary-based variant of :func:`ensure_message_continuity`."""

    if not messages:
        return messages

    message_objects = [Message.from_dict(msg) if not isinstance(msg, Message) else msg for msg in messages]
    sanitized_messages = ensure_message_continuity(message_objects)
    return [msg.to_dict() for msg in sanitized_messages]
