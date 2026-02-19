import json
from copy import deepcopy
from typing import Dict, List, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.utils.log import log_debug


def normalize_tool_messages(messages: List[Message]) -> List[Message]:
    """Normalize provider-specific tool messages into a standard per-tool format.

    Different model providers store tool call results differently:
    - Standard (OpenAI, Claude, Bedrock): each tool result is a separate Message
      with role="tool", content=string, tool_call_id=string at top level.
    - Gemini: all tool results are combined into ONE Message with role="tool",
      content=list, tool_calls=[{tool_call_id, tool_name, content}, ...].

    This function detects Gemini-style combined tool messages and splits them into
    individual per-tool messages so that any provider can consume them.

    Args:
        messages: List of messages to normalize.

    Returns:
        A new list of messages with combined tool messages expanded.
    """
    normalized: List[Message] = []

    for msg in messages:
        if msg.role == "tool" and _is_combined_tool_message(msg):
            normalized.extend(_split_combined_tool_message(msg))
        else:
            normalized.append(msg)

    return normalized


def _is_combined_tool_message(msg: Message) -> bool:
    """Detect if a message is a Gemini-style combined tool result message.

    A combined tool message has:
    - role="tool"
    - tool_call_id is None (not set at top level)
    - tool_calls is a non-empty list containing dicts with tool_name/tool_call_id
    - content is typically a list
    """
    if msg.role != "tool":
        return False

    # Must have tool_calls list with tool result entries
    if not msg.tool_calls or not isinstance(msg.tool_calls, list):
        return False

    # Must lack a top-level tool_call_id (standard messages have it)
    if msg.tool_call_id is not None:
        return False

    # The tool_calls entries should have tool_name (Gemini format)
    if len(msg.tool_calls) > 0:
        first = msg.tool_calls[0]
        if isinstance(first, dict) and "tool_name" in first:
            return True

    return False


def _split_combined_tool_message(msg: Message) -> List[Message]:
    """Split a Gemini-style combined tool message into individual tool messages.

    Args:
        msg: A combined tool message with tool_calls containing per-tool results.

    Returns:
        A list of individual tool messages in the standard format.
    """
    individual_messages: List[Message] = []
    content_list = msg.content if isinstance(msg.content, list) else []

    for idx, tool_call in enumerate(msg.tool_calls or []):
        if not isinstance(tool_call, dict):
            continue

        tool_call_id = tool_call.get("tool_call_id")
        tool_name = tool_call.get("tool_name")

        # Get content: prefer tool_call's own content, fall back to content list
        tc_content = tool_call.get("content")
        if tc_content is None and idx < len(content_list):
            tc_content = content_list[idx]

        # Ensure content is a string for standard format
        if tc_content is not None and not isinstance(tc_content, str):
            try:
                tc_content = json.dumps(tc_content) if not isinstance(tc_content, str) else tc_content
            except (TypeError, ValueError):
                tc_content = str(tc_content)

        individual_messages.append(
            Message(
                role="tool",
                content=tc_content,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                metrics=msg.metrics,
                from_history=msg.from_history,
                created_at=msg.created_at,
            )
        )

    return individual_messages


def filter_tool_calls(messages: List[Message], max_tool_calls: int) -> None:
    """
    Filter messages (in-place) to keep only the most recent N tool calls.

    Args:
        messages: List of messages to filter (modified in-place)
        max_tool_calls: Number of recent tool calls to keep
    """
    # Count total tool calls
    tool_call_count = sum(1 for m in messages if m.role == "tool")

    # No filtering needed
    if tool_call_count <= max_tool_calls:
        return

    # Collect tool_call_ids to keep (most recent N)
    tool_call_ids_list: List[str] = []
    for msg in reversed(messages):
        if msg.role == "tool" and len(tool_call_ids_list) < max_tool_calls:
            if msg.tool_call_id:
                tool_call_ids_list.append(msg.tool_call_id)

    tool_call_ids_to_keep: set[str] = set(tool_call_ids_list)

    # Filter messages in-place
    filtered_messages = []
    for msg in messages:
        if msg.role == "tool":
            # Keep only tool results in our window
            if msg.tool_call_id in tool_call_ids_to_keep:
                filtered_messages.append(msg)
        elif msg.role == "assistant" and msg.tool_calls:
            # Filter tool_calls within the assistant message
            # Use deepcopy to ensure complete isolation of the filtered message
            filtered_msg = deepcopy(msg)
            # Filter tool_calls
            if filtered_msg.tool_calls is not None:
                filtered_msg.tool_calls = [
                    tc for tc in filtered_msg.tool_calls if tc.get("id") in tool_call_ids_to_keep
                ]

            if filtered_msg.tool_calls:
                # Has tool_calls remaining, keep it
                filtered_messages.append(filtered_msg)
            # skip empty messages
            elif filtered_msg.content:
                filtered_msg.tool_calls = None
                filtered_messages.append(filtered_msg)
        else:
            filtered_messages.append(msg)

    messages[:] = filtered_messages

    # Log filtering information
    num_filtered = tool_call_count - len(tool_call_ids_to_keep)
    log_debug(f"Filtered {num_filtered} tool calls, kept {len(tool_call_ids_to_keep)}")


def get_text_from_message(message: Union[List, Dict, str, Message, BaseModel]) -> str:
    """Return the user texts from the message"""
    import json

    if isinstance(message, str):
        return message
    if isinstance(message, BaseModel):
        return message.model_dump_json(indent=2, exclude_none=True)
    if isinstance(message, list):
        text_messages = []
        if len(message) == 0:
            return ""

        # Check if it's a list of Message objects
        if isinstance(message[0], Message):
            for m in message:
                if isinstance(m, Message) and m.role == "user" and m.content is not None:
                    # Recursively extract text from the message content
                    content_text = get_text_from_message(m.content)
                    if content_text:
                        text_messages.append(content_text)
        elif "type" in message[0]:
            for m in message:
                m_type = m.get("type")
                if m_type is not None and isinstance(m_type, str):
                    m_value = m.get(m_type)
                    if m_value is not None and isinstance(m_value, str):
                        if m_type == "text":
                            text_messages.append(m_value)
                        # if m_type == "image_url":
                        #     text_messages.append(f"Image: {m_value}")
                        # else:
                        #     text_messages.append(f"{m_type}: {m_value}")
        elif "role" in message[0]:
            for m in message:
                m_role = m.get("role")
                if m_role is not None and isinstance(m_role, str):
                    m_content = m.get("content")
                    if m_content is not None and isinstance(m_content, str):
                        if m_role == "user":
                            text_messages.append(m_content)
        if len(text_messages) > 0:
            return "\n".join(text_messages)
    if isinstance(message, dict):
        if "content" in message:
            return get_text_from_message(message["content"])
        else:
            return json.dumps(message, indent=2)
    if isinstance(message, Message) and message.content is not None:
        return get_text_from_message(message.content)
    return ""
