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


def reconcile_tool_call_ids(messages: List[Message]) -> List[Message]:
    """
    Ensure tool result tool_call_id values match the corresponding assistant tool_calls[].id.

    The OpenAI Responses API stores two IDs per tool call: "id" (fc_*) and "call_id" (call_*).
    Its format_function_call_results translates tool_call_id to the call_id value. This creates
    a mismatch: assistant has id=fc_*, tool result has tool_call_id=call_*.

    This function builds a reverse map from call_id -> id and fixes tool results that reference
    a call_id instead of the canonical id. This is needed so that providers like Claude can match
    ToolUseBlock.id with tool_result.tool_use_id correctly.
    """
    # Build call_id -> id mapping from assistant tool_calls
    call_id_to_id: Dict[str, str] = {}
    known_ids: set = set()
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_id = tc.get("id")
                if tc_id:
                    known_ids.add(tc_id)
                    call_id = tc.get("call_id")
                    if call_id and call_id != tc_id:
                        call_id_to_id[call_id] = tc_id

    if not call_id_to_id:
        return messages

    # Fix tool results that reference call_id instead of id
    result: List[Message] = []
    for msg in messages:
        if (
            msg.role == "tool"
            and msg.tool_call_id
            and msg.tool_call_id not in known_ids
            and msg.tool_call_id in call_id_to_id
        ):
            msg_copy = msg.model_copy(deep=True)
            msg_copy.tool_call_id = call_id_to_id[msg.tool_call_id]
            result.append(msg_copy)
        else:
            result.append(msg)
    return result


def remap_tool_call_ids(messages: List[Message], prefix: str) -> List[Message]:
    """
    Remap tool call IDs across messages to use a target prefix.

    Different model providers use different ID prefixes:
    - OpenAI Chat Completions: "call_" (max 40 chars)
    - OpenAI Responses API: "fc_" (id) + "call_" (call_id)
    - Claude: "toolu_"
    - Gemini: varies

    This function builds a mapping from old IDs to new IDs with the target prefix,
    then updates both assistant tool_calls[].id and tool result message tool_call_id
    consistently. For the Responses API (prefix="fc_"), also generates a matching
    "call_" prefixed call_id.

    The Responses API stores tool_calls with both "id" (fc_*) and "call_id" (call_*),
    and its format_function_call_results translates tool result tool_call_id to the
    call_id value. So tool results may reference either the "id" or the "call_id" —
    both are mapped to the new ID.

    Args:
        messages: List of messages to process (returns new list, does not modify in-place).
        prefix: Target prefix for tool call IDs (e.g. "fc_", "call_").
    """
    # Build old -> new ID mapping from assistant tool_calls.
    # Map both tc["id"] and tc["call_id"] to the same new ID so tool results
    # referencing either value get remapped correctly.
    id_map: Dict[str, str] = {}
    call_id_map: Dict[str, str] = {}
    counter = 0
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                old_id = tc.get("id")
                if old_id and isinstance(old_id, str) and not old_id.startswith(prefix):
                    if old_id not in id_map:
                        new_id = f"{prefix}{counter:08x}"
                        id_map[old_id] = new_id

                        # Also map call_id -> new_id so tool results using call_id are found
                        existing_call_id = tc.get("call_id")
                        if existing_call_id and isinstance(existing_call_id, str) and existing_call_id != old_id:
                            id_map[existing_call_id] = new_id

                        # Generate a valid call_id for Responses API
                        if (
                            existing_call_id
                            and isinstance(existing_call_id, str)
                            and existing_call_id.startswith("call_")
                        ):
                            call_id_map[old_id] = existing_call_id
                        else:
                            call_id_map[old_id] = f"call_{counter:08x}"
                        counter += 1

    # No remapping needed
    if not id_map:
        return messages

    # Apply the mapping
    result: List[Message] = []
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            msg_copy = msg.model_copy(deep=True)
            if msg_copy.tool_calls:
                for tc in msg_copy.tool_calls:
                    old_id = tc.get("id")
                    if old_id and old_id in id_map:
                        tc["id"] = id_map[old_id]
                        tc["call_id"] = call_id_map.get(old_id, id_map[old_id])
            result.append(msg_copy)
        elif msg.role == "tool" and msg.tool_call_id and msg.tool_call_id in id_map:
            msg_copy = msg.model_copy(deep=True)
            msg_copy.tool_call_id = id_map[msg.tool_call_id]
            result.append(msg_copy)
        else:
            result.append(msg)
    return result


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
