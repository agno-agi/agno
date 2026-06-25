import base64
import json
import urllib.request
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Tuple

from ag_ui.core.types import Message as AGUIMessage
from ag_ui.core.types import Tool as AGUITool
from ag_ui.core.types import ToolMessage as AGUIToolMessage
from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.run.requirement import RunRequirement
from agno.tools.function import Function
from agno.utils.log import log_warning


def extract_user_input(messages: List[AGUIMessage]) -> str:
    # AG-UI sends full history; we only need the last user message
    for msg in reversed(messages):
        if msg.role == "user" and msg.content is not None:
            if isinstance(msg.content, str):
                return msg.content
            if isinstance(msg.content, list):
                text_parts = []
                for part in msg.content:
                    if hasattr(part, "type") and part.type == "text" and hasattr(part, "text"):
                        text_parts.append(part.text)
                if text_parts:
                    return "\n".join(text_parts)
    return ""


def extract_media(
    messages: List[AGUIMessage],
) -> Tuple[List[Image], List[Audio], List[Video], List[File]]:
    images: List[Image] = []
    audio: List[Audio] = []
    videos: List[Video] = []
    files: List[File] = []

    for msg in reversed(messages):
        if msg.role != "user" or msg.content is None:
            continue

        if isinstance(msg.content, str):
            return images, audio, videos, files

        for part in msg.content:
            if not hasattr(part, "type"):
                continue

            content: Optional[bytes] = None
            url: Optional[str] = None
            mime: Optional[str] = None
            filename: Optional[str] = None

            if part.type == "binary":
                # BinaryInputContent: flat structure
                mime = getattr(part, "mime_type", None)
                filename = getattr(part, "filename", None)
                url = getattr(part, "url", None)
                data = getattr(part, "data", None)
                if not url and data:
                    content = _decode_base64(data)

            elif part.type in ("image", "audio", "video", "document"):
                # ImageInputContent, AudioInputContent, etc: nested source
                source = getattr(part, "source", None)
                if source and hasattr(source, "type"):
                    mime = getattr(source, "mime_type", None)
                    value = getattr(source, "value", None)
                    if source.type == "url" and value:
                        url = value
                    elif source.type == "data" and value:
                        content = _decode_base64(value)

            # Route by part.type first, fall back to MIME for binary content
            if url or content:
                if part.type == "image" or (mime and mime.startswith("image/")):
                    images.append(Image(url=url, content=content, mime_type=mime))
                elif part.type == "audio" or (mime and mime.startswith("audio/")):
                    audio.append(Audio(url=url, content=content, mime_type=mime))
                elif part.type == "video" or (mime and mime.startswith("video/")):
                    videos.append(Video(url=url, content=content, mime_type=mime))
                else:
                    # File validates MIME — pass None for unsupported types to avoid raising
                    safe_mime = mime if mime in File.valid_mime_types() else None
                    files.append(File(url=url, content=content, mime_type=safe_mime, filename=filename))

        return images, audio, videos, files

    return images, audio, videos, files


def validate_state(state: Any, thread_id: str) -> Optional[Dict[str, Any]]:
    if state is None:
        return None

    if isinstance(state, dict):
        return state

    if isinstance(state, BaseModel):
        try:
            return state.model_dump()
        except Exception:
            pass

    if is_dataclass(state):
        try:
            return asdict(state)  # type: ignore
        except Exception:
            pass

    if hasattr(state, "to_dict") and callable(getattr(state, "to_dict")):
        try:
            result = state.to_dict()  # type: ignore
            if isinstance(result, dict):
                return result
        except Exception:
            pass

    log_warning(f"AGUI state must be a dict, got {type(state).__name__}. State will be ignored. Thread: {thread_id}")
    return None


def extract_context(context: Optional[List[Any]]) -> Optional[Dict[str, Any]]:
    # Convert AG-UI context list to Agno dependencies dict
    if not context:
        return None

    deps: Dict[str, Any] = {}
    for i, item in enumerate(context, start=1):
        key = item.description or f"context_{i}"
        value = item.value
        # AG-UI stringifies all values; parse JSON back to structured data
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass
        deps[key] = value
    return deps or None


def _decode_base64(value: str) -> Optional[bytes]:
    try:
        # data: URLs handled by urllib
        if value.startswith("data:"):
            return urllib.request.urlopen(value).read()
        return base64.b64decode(value, validate=True)
    except Exception:
        log_warning("Failed to decode base64 content")
        return None


def extract_tool_messages(messages: List[AGUIMessage]) -> List[AGUIToolMessage]:
    # Trailing tool messages = frontend executed tools and sent results back
    tool_msgs: List[AGUIToolMessage] = []
    for msg in reversed(messages):
        if msg.role == "tool":
            tool_msgs.append(msg)  # type: ignore[arg-type]
        else:
            break
    return list(reversed(tool_msgs))


def agui_tools_to_external_functions(agui_tools: Optional[List[AGUITool]]) -> List[Function]:
    # Frontend tools run in the browser; external_execution=True pauses the run
    if not agui_tools:
        return []
    return [
        Function(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters or {"type": "object", "properties": {}},
            external_execution=True,
            external_execution_silent=True,
        )
        for tool in agui_tools
    ]


def merge_tool_results_into_requirements(
    stored_requirements: List[RunRequirement],
    tool_messages: List[AGUIToolMessage],
) -> List[RunRequirement]:
    # Fill in tool results from ToolMessages into stored requirements
    results_map = {tm.tool_call_id: (tm.content, getattr(tm, "error", None)) for tm in tool_messages}

    for req in stored_requirements:
        if req.tool_execution and req.tool_execution.tool_call_id:
            tool_call_id = req.tool_execution.tool_call_id
            if tool_call_id in results_map:
                content, error = results_map[tool_call_id]
                if error:
                    req.tool_execution.tool_call_error = True
                    req.tool_execution.result = error
                else:
                    req.tool_execution.result = content
                req.external_execution_result = req.tool_execution.result

    return stored_requirements


def build_tool_results_map(tool_messages: List[AGUIToolMessage]) -> Dict[str, str]:
    return {tm.tool_call_id: tm.content for tm in tool_messages}
