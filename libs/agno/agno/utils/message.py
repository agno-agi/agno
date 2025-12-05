from copy import deepcopy
from typing import Dict, List, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.utils.log import log_debug


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
