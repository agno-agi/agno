from copy import deepcopy
from typing import Dict, List, Optional, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.utils.log import log_debug


def normalize_tool_messages(messages: List[Message]) -> List[Message]:
    """
    Split combined tool result messages into individual canonical messages.

    Older Gemini sessions stored all tool results in a single Message with:
      role="tool", tool_call_id=None, content=[list],
      tool_calls=[{"tool_call_id": ..., "tool_name": ..., "content": ...}, ...]

    This function detects that format and expands each entry into a separate
    canonical Message(role="tool", tool_call_id=..., tool_name=..., content=...).

    Messages already in canonical format are passed through unchanged.
    """
    result: List[Message] = []
    for msg in messages:
        if msg.role == "tool" and msg.tool_call_id is None and msg.tool_calls and isinstance(msg.tool_calls, list):
            # Combined format — split into individual messages
            content_list = msg.content if isinstance(msg.content, list) else []
            for idx, tc in enumerate(msg.tool_calls):
                # Prefer original content from the list, fall back to tool_call content
                if idx < len(content_list):
                    tc_content = content_list[idx]
                else:
                    tc_content = tc.get("content", "")
                split_msg = Message(
                    role="tool",
                    tool_call_id=tc.get("tool_call_id"),
                    tool_name=tc.get("tool_name"),
                    content=tc_content,
                )
                if idx == 0 and msg.metrics is not None:
                    split_msg.metrics = msg.metrics
                result.append(split_msg)
        else:
            result.append(msg)
    return result


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


# ---------------------------------------------------------------------------
# Provider tool call ID configuration
# ---------------------------------------------------------------------------

# Each provider has different requirements for tool call IDs.
# Add new providers here as needed.
PROVIDER_TOOL_ID_CONFIG: Dict[str, Dict[str, Union[str, int, None]]] = {
    "openai_chat": {
        "prefix": "call_",
        "max_length": 40,
        "call_id_prefix": None,  # No separate call_id needed
    },
    "openai_responses": {
        "prefix": "fc_",
        "max_length": None,
        "call_id_prefix": "call_",  # Responses API requires a separate call_id with call_* prefix
    },
    "claude": {
        "prefix": "toolu_",
        "max_length": None,
        "call_id_prefix": None,
    },
    "gemini": {
        "prefix": None,  # Accepts any format — no reformatting needed
        "max_length": None,
        "call_id_prefix": None,
    },
    "mistral": {
        "prefix": "",  # Alphanumeric only, length 9 — reformat all foreign IDs
        "max_length": 9,
        "call_id_prefix": None,
    },
}


def reformat_tool_call_ids(messages: List[Message], provider: str) -> List[Message]:
    """
    Reformat tool call IDs to match a provider's requirements.

    Each provider has different ID prefix and length constraints (see PROVIDER_TOOL_ID_CONFIG).
    This function builds a mapping from foreign IDs to new IDs with the target prefix,
    then updates both assistant tool_calls[].id and tool result message tool_call_id
    consistently.

    For providers with a call_id_prefix (e.g. OpenAI Responses), also generates a matching
    call_id on each tool call.

    Args:
        messages: List of messages to process (returns new list, does not modify in-place).
        provider: Provider key from PROVIDER_TOOL_ID_CONFIG (e.g. "openai_chat", "openai_responses").
    """
    config = PROVIDER_TOOL_ID_CONFIG.get(provider)
    if config is None:
        return messages

    prefix = config.get("prefix")
    if prefix is None:
        # Provider accepts any ID format — no reformatting needed
        return messages

    max_length: Optional[int] = config.get("max_length")  # type: ignore[assignment]
    call_id_prefix: Optional[str] = config.get("call_id_prefix")  # type: ignore[assignment]

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
                if not (old_id and isinstance(old_id, str)):
                    continue

                # Reformat if wrong prefix, exceeds max length, or has invalid chars
                needs_reformat = not old_id.startswith(prefix)
                if not needs_reformat and max_length and len(old_id) > max_length:
                    needs_reformat = True
                # When prefix is "" (e.g. Mistral), also reformat if ID contains non-alphanumeric chars
                if not needs_reformat and prefix == "" and not old_id.isalnum():
                    needs_reformat = True

                if needs_reformat and old_id not in id_map:
                    # Generate ID with enough hex digits to fill max_length (or 8 by default)
                    prefix_len = len(prefix) if isinstance(prefix, str) else 0
                    id_digits = (max_length - prefix_len) if max_length else 8
                    new_id = f"{prefix}{counter:0{id_digits}x}"
                    id_map[old_id] = new_id

                    # Also map call_id -> new_id so tool results using call_id are found
                    existing_call_id = tc.get("call_id")
                    if existing_call_id and isinstance(existing_call_id, str) and existing_call_id != old_id:
                        id_map[existing_call_id] = new_id

                    # Generate a matching call_id if the provider requires one
                    if call_id_prefix:
                        if (
                            existing_call_id
                            and isinstance(existing_call_id, str)
                            and existing_call_id.startswith(call_id_prefix)
                        ):
                            call_id_map[old_id] = existing_call_id
                        else:
                            call_id_map[old_id] = f"{call_id_prefix}{counter:08x}"

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
                        if call_id_prefix:
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
