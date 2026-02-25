import copy
import json
from typing import Any, List, Optional, Union

from agno.models.message import Message
from agno.utils.log import log_warning


def _coerce_to_str(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, list):
        return "\n".join(_coerce_to_str(v) for v in value if v is not None)
    if value is None:
        return ""
    return str(value)


def resolve_tool_call_id(tc: dict) -> Optional[str]:
    for key in ("tool_call_id", "id", "call_id"):
        val = tc.get(key)
        if val is not None:
            return str(val)
    return None


def tool_result_text(value: Any) -> str:
    return _coerce_to_str(value)


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
        if msg.tool_call_id is None and msg.tool_calls:
            content_list = msg.content if isinstance(msg.content, list) else None
            names = [n.strip() for n in msg.tool_name.split(",")] if msg.tool_name and "," in msg.tool_name else None

            for idx, tc in enumerate(msg.tool_calls):
                tc_id = resolve_tool_call_id(tc)
                tc_name = tc.get("tool_name")
                if not tc_name and names and idx < len(names):
                    tc_name = names[idx]

                if tc_id is None:
                    log_warning(f"Skipping tool call entry with no ID in combined message (tool_name={tc_name})")
                    continue

                # Resolve content: prefer positional from content list, then scalar msg.content, then tc entry
                original: Optional[Union[List[Any], str]] = None
                if content_list and idx < len(content_list):
                    original = content_list[idx]
                elif msg.content is not None and not isinstance(msg.content, list):
                    original = msg.content

                content_value = original if original is not None else tc.get("content")

                final_content: Optional[str] = None
                if content_value is not None:
                    final_content = (
                        _coerce_to_str(content_value) if not isinstance(content_value, str) else content_value
                    )

                compressed: Optional[str] = None
                if compress_tool_results:
                    raw = tc.get("content")
                    if raw is not None:
                        compressed = raw if isinstance(raw, str) else _coerce_to_str(raw)

                normalized.append(
                    Message(
                        role="tool",
                        content=final_content,
                        compressed_content=compressed,
                        tool_call_id=tc_id,
                        tool_name=tc_name,
                        metrics=copy.copy(msg.metrics),
                        provider_data=msg.provider_data,
                        from_history=msg.from_history,
                        created_at=msg.created_at,
                    )
                )
            continue

        # Case 2: Normalize list content to string
        if isinstance(msg.content, list):
            msg = msg.model_copy(update={"content": _coerce_to_str(msg.content)})

        if msg.tool_call_id is None:
            log_warning(f"Tool message missing tool_call_id (tool_name={msg.tool_name})")

        normalized.append(msg)

    return normalized
