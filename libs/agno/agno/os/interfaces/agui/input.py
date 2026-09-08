import base64
import json
import urllib.request
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from ag_ui.core.types import Message as AGUIMessage
from ag_ui.core.types import Tool as AGUITool
from ag_ui.core.types import ToolMessage as AGUIToolMessage
from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_warning

_FORWARDABLE_ROLES = ("user", "assistant", "tool")


def extract_current_turn(
    messages: List[AGUIMessage],
) -> Tuple[str, List[Image], List[Audio], List[Video], List[File]]:
    """The text and media of the message this request is asking about.

    Resolved and decoded once. Reading text from one message and media from another would
    make a single turn out of two, so this is one message: the newest user message that
    carries anything.

    An empty newest user message is not the turn. Some clients append one before the user
    has typed, and taking it would ask the model nothing. Reaching back past it means the
    newest question the user did ask is asked again, and the answer it already got is not
    history, because this run is about to produce that answer afresh. When no user message
    carries anything the newest one is the turn regardless, so an all-empty transcript
    still has a turn rather than becoming all history.
    """
    index = _current_turn_index(messages)
    if index is None:
        return "", [], [], [], []

    content = _model_facing_content(messages[index])
    if content is None:
        return _message_text(messages[index]) or "", [], [], [], []
    return content


def extract_user_input(messages: List[AGUIMessage]) -> str:
    """Extract the current turn's text from AG-UI messages."""
    return extract_current_turn(messages)[0]


def extract_media(
    messages: List[AGUIMessage],
) -> Tuple[List[Image], List[Audio], List[Video], List[File]]:
    """Extract media from the current turn."""
    _, images, audio, videos, files = extract_current_turn(messages)
    return images, audio, videos, files


def _current_turn_index(messages: List[AGUIMessage]) -> Optional[int]:
    """Index of the newest user message that carries anything, else the newest one."""
    fallback: Optional[int] = None

    for index in range(len(messages) - 1, -1, -1):
        msg = messages[index]
        if msg.role != "user":
            continue
        if _model_facing_content(msg) is not None:
            return index
        if fallback is None:
            fallback = index

    return fallback


def _message_text(msg: AGUIMessage) -> Optional[str]:
    """The text an AG-UI message contributes, or None when it carries none."""
    if isinstance(msg.content, str):
        return msg.content

    if isinstance(msg.content, list):
        # Empty parts are dropped rather than joined: they would only add blank lines.
        text_parts = [
            text
            for part in msg.content
            if getattr(part, "type", None) == "text" and (text := getattr(part, "text", None))
        ]
        if text_parts:
            return "\n".join(text_parts)

    return None


def _extract_media_from_content(
    content: Any,
) -> Tuple[List[Image], List[Audio], List[Video], List[File]]:
    """Extract media from one message's content parts."""
    images: List[Image] = []
    audio: List[Audio] = []
    videos: List[Video] = []
    files: List[File] = []

    if not isinstance(content, list):
        return images, audio, videos, files

    for part in content:
        if not hasattr(part, "type"):
            continue

        # Extract content bytes and MIME type based on part structure
        part_content: Optional[bytes] = None
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
                part_content = _decode_base64(data)

        elif part.type in ("image", "audio", "video", "document"):
            # AG-UI wraps media in a source object with type (url/data) and value
            source = getattr(part, "source", None)
            if source and hasattr(source, "type"):
                mime = getattr(source, "mime_type", None)
                value = getattr(source, "value", None)
                if source.type == "url" and value:
                    url = value
                elif source.type == "data" and value:
                    part_content = _decode_base64(value)

        if url or part_content:
            if part.type == "image" or (mime and mime.startswith("image/")):
                images.append(Image(url=url, content=part_content, mime_type=mime))
            elif part.type == "audio" or (mime and mime.startswith("audio/")):
                audio.append(Audio(url=url, content=part_content, mime_type=mime))
            elif part.type == "video" or (mime and mime.startswith("video/")):
                videos.append(Video(url=url, content=part_content, mime_type=mime))
            else:
                # File validates MIME — pass None for unsupported types to avoid raising
                safe_mime = mime if mime in File.valid_mime_types() else None
                files.append(File(url=url, content=part_content, mime_type=safe_mime, filename=filename))

    return images, audio, videos, files


def _prior_messages(messages: List[AGUIMessage]) -> List[AGUIMessage]:
    """The messages that precede the current turn.

    Anything after the newest user message answers that same message, and this request is
    about to produce that answer again, so it is not history either.
    """
    index = _current_turn_index(messages)
    prior = messages if index is None else messages[:index]
    # Filtered here rather than skipped while walking: an activity or reasoning message
    # between a tool call and its result would otherwise cut the block in half.
    return [msg for msg in prior if msg.role in _FORWARDABLE_ROLES]


def _model_facing_content(
    msg: AGUIMessage,
) -> Optional[Tuple[str, List[Image], List[Audio], List[Video], List[File]]]:
    """The text and media a user message contributes, or None when it contributes nothing.

    An empty turn costs tokens and some providers reject it, so a message that decodes to
    nothing is neither forwarded nor chosen as the current turn. Media is decoded only
    when there is no text to settle it, which is the common case.
    """
    text = _message_text(msg) or ""
    if text.strip():
        return (text, *_extract_media_from_content(msg.content))

    media = _extract_media_from_content(msg.content)
    if not any(media):
        return None
    return (text, *media)


def extract_message_history(messages: List[AGUIMessage]) -> List[Message]:
    """Convert the conversation that precedes the current turn into Agno messages.

    The contract is deliberately narrow, because the obvious wider one duplicates
    messages. The result is history and nothing else:

    - The current turn is excluded, and so is anything after it: the turn reaches the
      model as ``extract_user_input`` plus ``extract_media``, and a reply that follows it
      is the answer this run is about to produce again.
    - Client system and developer messages are excluded: the entity owns its system
      message, and a second one inserted mid-conversation would fight it.
    - Activity and reasoning messages are excluded: they carry no model-facing content.
    - A message with neither text, media nor a forwarded tool call is excluded: an empty
      turn costs tokens and some providers reject it.
    - Tool traffic is forwarded as blocks, which is the shape providers accept: an
      assistant turn's calls followed immediately by their results. A call whose result
      does not arrive in that block is dropped along with the result, a call id is
      forwarded at most once however often the client reuses it, and a result carrying
      neither content nor an error does not count as one.
    - History starts at a user message. Providers reject a conversation that opens on an
      assistant turn, which is what a client's opening greeting would produce.

    The whole transcript the client sent is forwarded. ``num_history_runs`` and
    ``num_history_messages`` are not applied: they window a session this path does not
    read, and the first of them defaults to three runs, so applying it would silently
    drop conversation.

    Only a caller that suppresses the entity's own history for the same run may forward
    this. An entity reading a session as well would see the conversation twice.
    """
    prior = _prior_messages(messages)

    history: List[Message] = []
    forwarded_calls: Set[str] = set()
    index = 0

    while index < len(prior):
        msg = prior[index]

        if msg.role == "user":
            index += 1
            content = _model_facing_content(msg)
            if content is None:
                continue
            text, images, audio, videos, files = content
            history.append(
                Message(
                    role="user",
                    # Media with no caption keeps the empty string Agno's own user message
                    # uses for that case, so providers see one shape, not two.
                    content=text,
                    images=images or None,
                    audio=audio or None,
                    videos=videos or None,
                    files=files or None,
                    from_history=True,
                )
            )
            continue

        if msg.role != "assistant":
            # A tool result outside an assistant's own block answers nothing.
            index += 1
            continue

        results, index = _tool_results_following(prior, index + 1)
        answered = [
            tool_call
            for tool_call in _unique_tool_calls(msg)
            if tool_call.id in results and tool_call.id not in forwarded_calls
        ]

        if not msg.content and not answered:
            continue
        if not history:
            # Nothing to answer yet: an assistant turn cannot open the conversation.
            continue

        history.append(
            Message(
                role="assistant",
                content=msg.content,
                tool_calls=[
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments},
                    }
                    for tool_call in answered
                ]
                or None,
                from_history=True,
            )
        )
        for tool_call in answered:
            forwarded_calls.add(tool_call.id)
            result = results[tool_call.id]
            error = getattr(result, "error", None)
            history.append(
                Message(
                    role="tool",
                    tool_call_id=tool_call.id,
                    # Gemini formats a tool message with no tool_name as plain text, which
                    # leaves the call it answers unanswered. The name comes from the call
                    # so the two can never disagree.
                    tool_name=tool_call.function.name,
                    # Both halves ride along: the result the frontend produced before it
                    # failed is context, and dropping the error replays a failure as a
                    # success.
                    content="\n".join(part for part in (result.content, error) if part),
                    tool_call_error=bool(error),
                    from_history=True,
                )
            )

    return history


def _unique_tool_calls(msg: AGUIMessage) -> List[Any]:
    """An assistant message's tool calls, first occurrence of each id."""
    seen: Set[str] = set()
    unique: List[Any] = []
    for tool_call in getattr(msg, "tool_calls", None) or []:
        if tool_call.id in seen:
            continue
        seen.add(tool_call.id)
        unique.append(tool_call)
    return unique


def _tool_results_following(prior: List[AGUIMessage], index: int) -> Tuple[Dict[str, Any], int]:
    """The tool results in the block that starts at ``index``, and where the block ends.

    Only results that carry something count: a result with neither content nor an error
    tells the model nothing, and forwarding the call it answers without it would leave
    the call unanswered.
    """
    results: Dict[str, Any] = {}

    while index < len(prior) and prior[index].role == "tool":
        result = prior[index]
        index += 1
        call_id = getattr(result, "tool_call_id", None)
        if not call_id or not (result.content or getattr(result, "error", None)):
            continue
        results.setdefault(call_id, result)

    return results, index


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


def parse_client_tools(agui_tools: Optional[List[AGUITool]]) -> List[Function]:
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
