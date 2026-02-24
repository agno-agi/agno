import copy
from typing import Any, List, Optional, Union

from agno.models.message import Message
from agno.utils.log import log_warning


def tool_result_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value if v is not None)
    return str(value)


def normalize_tool_result_messages(
    messages: List[Message],
    *,
    compress_tool_results: bool = False,
) -> List[Message]:
    normalized: List[Message] = []

    for msg in messages:
        if msg.role != "tool":
            normalized.append(msg)
            continue

        # Case 1: Gemini combined tool message
        # Detection: role="tool", no top-level tool_call_id, has tool_calls list
        # Use `is None` (not falsy check) so empty-string IDs are treated as present
        if msg.tool_call_id is None and msg.tool_calls:
            content_list = msg.content if isinstance(msg.content, list) else None

            for idx, tc in enumerate(msg.tool_calls):
                tc_id = tc.get("tool_call_id") or tc.get("id") or tc.get("call_id")
                if tc_id is not None:
                    tc_id = str(tc_id)
                tc_name = tc.get("tool_name")

                if not tc_name and msg.tool_name and "," in msg.tool_name:
                    names = [n.strip() for n in msg.tool_name.split(",")]
                    if idx < len(names):
                        tc_name = names[idx]

                # Original content from the content list
                original: Optional[Union[List[Any], str]] = None
                if content_list and idx < len(content_list):
                    original = content_list[idx]
                elif msg.content is not None and not isinstance(msg.content, list):
                    original = msg.content

                # Compressed content from tool_calls entry (must be string for Message.compressed_content)
                compressed_raw = tc.get("content") if compress_tool_results else None
                compressed = (
                    tool_result_text(compressed_raw)
                    if compressed_raw is not None and not isinstance(compressed_raw, str)
                    else compressed_raw
                )

                # Final content: prefer original, fall back to tc content
                content_value = original if original is not None else tc.get("content")

                if tc_id is None:
                    log_warning(f"Skipping tool call entry with no ID in combined message (tool_name={tc_name})")
                    continue

                # Ensure content is a type accepted by Message (str, list, or None)
                final_content: Optional[str] = None
                if isinstance(content_value, dict):
                    final_content = str(content_value)
                elif isinstance(content_value, list):
                    final_content = tool_result_text(content_value)
                elif isinstance(content_value, str):
                    final_content = content_value
                elif content_value is not None:
                    final_content = str(content_value)

                new_msg = Message(
                    role="tool",
                    content=final_content,
                    compressed_content=compressed if compressed is not None else None,
                    tool_call_id=tc_id,
                    tool_name=tc_name,
                    metrics=copy.copy(msg.metrics),
                    provider_data=msg.provider_data,
                    from_history=msg.from_history,
                    created_at=msg.created_at,
                )
                normalized.append(new_msg)
            continue

        # Case 2: Normalize list content to string
        if isinstance(msg.content, list):
            msg = msg.model_copy(update={"content": tool_result_text(msg.content)})

        if msg.tool_call_id is None:
            log_warning(f"Tool message missing tool_call_id (tool_name={msg.tool_name})")

        normalized.append(msg)

    return normalized
