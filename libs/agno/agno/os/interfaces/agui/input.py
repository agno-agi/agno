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
    """Extract the last user message content from AG-UI messages."""
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
    """Extract media from the last user message."""
    images: List[Image] = []
    audio: List[Audio] = []
    videos: List[Video] = []
    files: List[File] = []

    # 1. Find the last user message
    for msg in reversed(messages):
        if msg.role != "user" or msg.content is None:
            continue

        # String content has no media
        if isinstance(msg.content, str):
            return images, audio, videos, files

        # 2. Process each content part
        for part in msg.content:
            if not hasattr(part, "type"):
                continue

            # 3. Extract content bytes and MIME type based on part structure
            content: Optional[bytes] = None
            url: Optional[str] = None
            mime: Optional[str] = None
            filename: Optional[str] = None

            if part.type == "binary":
                # BinaryInputContent: flat structure (deprecated but still used)
                mime = getattr(part, "mime_type", None)
                filename = getattr(part, "filename", None)
                url = getattr(part, "url", None)
                data = getattr(part, "data", None)
                if not url and data:
                    content = _decode_base64(data)

            elif part.type in ("image", "audio", "video", "document"):
                # AG-UI wraps media in a source object with type (url/data) and value
                source = getattr(part, "source", None)
                if source and hasattr(source, "type"):
                    mime = getattr(source, "mime_type", None)
                    value = getattr(source, "value", None)
                    if source.type == "url" and value:
                        url = value
                    elif source.type == "data" and value:
                        content = _decode_base64(value)

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
    """Validate the given AGUI state is of the expected type (dict)."""
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
    """Convert AG-UI context list to a dependencies dict."""
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
    """Decode base64 string to bytes. Handles data: URLs and raw base64."""
    try:
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


def _parse_payload(content: Any) -> Dict[str, Any]:
    """Tolerantly parse a ToolMessage.content JSON string into a dict (empty dict on failure)."""
    if isinstance(content, dict):
        return content
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def merge_tool_results_into_requirements(
    stored_requirements: List[RunRequirement],
    tool_messages: List[AGUIToolMessage],
) -> List[RunRequirement]:
    """Resolve each paused requirement from its matching inbound ToolMessage, BY pause_type.

    ToolMessage.content is a developer-defined JSON string (AG-UI defines no HITL payload
    schema), so the frontend registration MUST emit exactly what this parses. Matching is by
    tool_call_id; the branch is chosen by the STORED requirement's pause_type, never the payload:
      - confirmation:       {"accepted": <bool>}   (optional "note")
      - user_input:         {"values": {<field>: <value>, ...}}   (required; a non-dict "values" raises)
      - external_execution: the raw result string, passed through unchanged

    Crucially, confirmation/user_input set confirmed/answered (NOT result) so agno runs the
    backend tool on resume. Only external_execution sets result - setting a result on a
    confirmation would make agno's dispatch reject the tool instead of running it.
    """
    results_map = {tm.tool_call_id: (tm.content, getattr(tm, "error", None)) for tm in tool_messages}
    for req in stored_requirements:
        te = req.tool_execution
        if not te or not te.tool_call_id or te.tool_call_id not in results_map:
            continue
        content, error = results_map[te.tool_call_id]
        data = _parse_payload(content)
        pause_type = req.pause_type
        # user_feedback is out of V0 scope and never emitted; an unhandled pause_type falls through
        # here and ensure_requirements_resolved raises on it (fail-loud, never a silent skip).
        if pause_type == "external_execution":
            if error:
                te.tool_call_error = True
            req.set_external_execution_result(error if error else content)
        elif pause_type == "confirmation":
            if error or data.get("accepted") is not True:
                req.reject(note=data.get("note") or error)
            else:
                req.confirm()
        elif pause_type == "user_input":
            values = data.get("values")
            if not isinstance(values, dict):
                raise ValueError("user_input resume expects a {'values': {...}} object")
            req.provide_user_input(values)
    return stored_requirements


def ensure_requirements_resolved(requirements: List[RunRequirement]) -> None:
    """Raise if any paused requirement is left unresolved (a partial multi-tool answer).

    On a multi-tool pause the frontend may answer only some tools; merge_tool_results_into_requirements
    skips the unanswered ones, leaving them unresolved. Passing a partial set to acontinue_run would let
    those unanswered confirmation tools reach dispatch and be silently rejected. Fail loudly
    instead - the frontend must answer every paused tool in one resume.
    """
    unresolved = [r for r in requirements if not r.is_resolved()]
    if unresolved:
        names = ", ".join(
            r.tool_execution.tool_name for r in unresolved if r.tool_execution and r.tool_execution.tool_name
        )
        raise ValueError(
            f"Partial resume: {len(unresolved)} of {len(requirements)} paused tool(s) unanswered"
            + (f" ({names})" if names else "")
            + ". The frontend must answer all paused tools before resuming."
        )


def build_tool_results_map(tool_messages: List[AGUIToolMessage]) -> Dict[str, str]:
    return {tm.tool_call_id: tm.content for tm in tool_messages}
