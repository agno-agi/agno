"""Logic used by the AG-UI router."""

import base64
import copy
import json
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple, Type, TypeVar, Union

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    RawEvent,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunFinishedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.core.types import Message as AGUIMessage
from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.reasoning.step import ReasoningStep
from agno.run.agent import ReasoningCompletedEvent as AgentReasoningCompletedEvent
from agno.run.agent import ReasoningContentDeltaEvent as AgentReasoningContentDeltaEvent
from agno.run.agent import ReasoningStartedEvent as AgentReasoningStartedEvent
from agno.run.agent import ReasoningStepEvent as AgentReasoningStepEvent
from agno.run.agent import RunContentEvent, RunEvent, RunOutputEvent, RunPausedEvent
from agno.run.team import ReasoningCompletedEvent as TeamReasoningCompletedEvent
from agno.run.team import ReasoningContentDeltaEvent as TeamReasoningContentDeltaEvent
from agno.run.team import ReasoningStartedEvent as TeamReasoningStartedEvent
from agno.run.team import ReasoningStepEvent as TeamReasoningStepEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import TeamRunEvent, TeamRunOutputEvent
from agno.utils.log import log_warning
from agno.utils.message import get_text_from_message


def validate_agui_state(state: Any, thread_id: str) -> Optional[Dict[str, Any]]:
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


@dataclass
class EventBuffer:
    """Buffer to manage event ordering constraints, relevant when mapping Agno responses to AG-UI events."""

    active_tool_call_ids: Set[str]  # All currently active tool calls
    ended_tool_call_ids: Set[str]  # All tool calls that have ended
    current_text_message_id: str = ""  # ID of the current text message context (for tool call parenting)
    next_text_message_id: str = ""  # Pre-generated ID for the next text message
    pending_tool_calls_parent_id: str = ""  # Parent message ID for pending tool calls
    reasoning_message_id: Optional[str] = None  # Active reasoning session ID, set by reasoning_started
    reasoning_step_count: int = 0  # Step counter for ReasoningTools (reset each session)
    _last_snapshot: Optional[Dict[str, Any]] = field(
        default=None, repr=False
    )  # Snapshot of last state for delta computation

    def __init__(self):
        self.active_tool_call_ids = set()
        self.ended_tool_call_ids = set()
        self.current_text_message_id = ""
        self.next_text_message_id = str(uuid.uuid4())
        self.pending_tool_calls_parent_id = ""
        self.reasoning_message_id = None
        self.reasoning_step_count = 0
        self._last_snapshot = None

    def start_tool_call(self, tool_call_id: str) -> None:
        """Start a new tool call."""
        self.active_tool_call_ids.add(tool_call_id)

    def end_tool_call(self, tool_call_id: str) -> None:
        """End a tool call."""
        self.active_tool_call_ids.discard(tool_call_id)
        self.ended_tool_call_ids.add(tool_call_id)

    def start_text_message(self) -> str:
        """Start a new text message and return its ID."""
        # Use the pre-generated next ID as current, and generate a new next ID
        self.current_text_message_id = self.next_text_message_id
        self.next_text_message_id = str(uuid.uuid4())
        return self.current_text_message_id

    def get_parent_message_id_for_tool_call(self) -> str:
        """Get the message ID to use as parent for tool calls."""
        # If we have a pending parent ID set (from text message end), use that
        if self.pending_tool_calls_parent_id:
            return self.pending_tool_calls_parent_id
        # Otherwise use current text message ID
        return self.current_text_message_id

    def set_pending_tool_calls_parent_id(self, parent_id: str) -> None:
        """Set the parent message ID for upcoming tool calls."""
        self.pending_tool_calls_parent_id = parent_id

    def clear_pending_tool_calls_parent_id(self) -> None:
        """Clear the pending parent ID when a new text message starts."""
        self.pending_tool_calls_parent_id = ""

    def start_reasoning(self) -> str:
        """Start a new reasoning session and return its message ID."""
        self.reasoning_message_id = str(uuid.uuid4())
        self.reasoning_step_count = 0
        return self.reasoning_message_id

    def set_state_snapshot(self, state: Dict[str, Any]) -> None:
        """Store deep copy of current state for delta computation."""
        self._last_snapshot = copy.deepcopy(state)

    def compute_state_delta(self, current_state: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Compute JSON Patch delta between last snapshot and current state.

        Returns a list of JSON Patch ops (RFC 6902) or None if unchanged/error.
        """
        if self._last_snapshot is None:
            return None
        try:
            import jsonpatch

            patch = jsonpatch.make_patch(self._last_snapshot, current_state)
            ops = patch.patch
            if not ops:
                return None
            return ops
        except Exception as e:
            log_warning(f"Failed to compute state delta: {e}")
            return None

    def next_reasoning_step(self) -> int:
        """Increment and return the current reasoning step number."""
        self.reasoning_step_count += 1
        return self.reasoning_step_count

    def ensure_reasoning_started(self) -> Tuple[str, bool]:
        """Return the active reasoning session ID, starting one if needed.
        Returns (reasoning_id, is_new) where is_new is True if a new session was created.
        """
        if self.reasoning_message_id is not None:
            return self.reasoning_message_id, False
        return self.start_reasoning(), True

    def end_reasoning(self) -> None:
        """End the active reasoning session."""
        self.reasoning_message_id = None
        self.reasoning_step_count = 0


# MIME types whose Agno `format` differs from the raw subtype (e.g. OpenAI audio expects "mp3")
_MIME_TO_FORMAT: Dict[str, str] = {
    "audio/mpeg": "mp3",
}


def _format_from_mime_type(mime_type: Optional[str]) -> Optional[str]:
    """Return the Agno media `format` for a MIME type (e.g. 'image/png' -> 'png'), or None."""
    if not mime_type or "/" not in mime_type:
        return None
    return _MIME_TO_FORMAT.get(mime_type, mime_type.split("/")[-1])


def _decode_agui_base64_content(value: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Decode an AG-UI base64 value and return bytes plus any data URL MIME type."""
    mime_type = None
    encoded_value = value

    if value.startswith("data:") and "," in value:
        metadata, encoded_value = value.split(",", 1)
        if metadata.startswith("data:"):
            mime_type = metadata[5:].split(";", 1)[0] or None

    try:
        return base64.b64decode(encoded_value, validate=True), mime_type
    except ValueError:  # b64decode raises binascii.Error or UnicodeEncodeError, both ValueError subclasses
        log_warning("Failed to decode AG-UI data source. Content part will be ignored.")
        return None, mime_type


def _safe_file_mime_type(mime_type: Optional[str]) -> Optional[str]:
    """Return the MIME type only if it is a valid Agno File MIME type, else None."""
    if mime_type in File.valid_mime_types():
        return mime_type
    return None


@dataclass
class AGUIUserInputMedia:
    """Media extracted from an AG-UI user message."""

    images: List[Image] = field(default_factory=list)
    audio: List[Audio] = field(default_factory=list)
    videos: List[Video] = field(default_factory=list)
    files: List[File] = field(default_factory=list)


# AG-UI typed media content type -> (Agno media class, AGUIUserInputMedia field, sanitize MIME)
_AGUI_MEDIA_PARTS: Dict[str, Tuple[type, str, bool]] = {
    "image": (Image, "images", False),
    "audio": (Audio, "audio", False),
    "video": (Video, "videos", False),
    "document": (File, "files", True),
}


_AGUIMedia = TypeVar("_AGUIMedia", Image, Audio, Video, File)


def _extract_agui_media(part: Any, media_cls: Type[_AGUIMedia], sanitize_mime: bool = False) -> Optional[_AGUIMedia]:
    """Convert a typed AG-UI input content part into the given Agno media object."""
    source = getattr(part, "source", None)
    if source is None:
        return None

    source_type = getattr(source, "type", None)
    value = getattr(source, "value", None)
    if not value:
        return None

    mime_type = getattr(source, "mime_type", None)
    content_kwargs: Dict[str, Any]
    if source_type == "url":
        content_kwargs = {"url": value}
    elif source_type == "data":
        content, data_url_mime_type = _decode_agui_base64_content(value)
        if content is None:
            return None
        content_kwargs = {"content": content}
        mime_type = mime_type or data_url_mime_type
    else:
        return None

    extra_kwargs: Dict[str, Any] = {}
    # filename is only carried on File (document) media; Image/Audio/Video have no such field
    if media_cls is File:
        metadata = getattr(part, "metadata", None)
        filename = metadata.get("filename") if isinstance(metadata, dict) else None
        if filename:
            extra_kwargs["filename"] = filename

    return media_cls(
        format=_format_from_mime_type(mime_type),
        mime_type=_safe_file_mime_type(mime_type) if sanitize_mime else mime_type,
        **extra_kwargs,
        **content_kwargs,
    )


def _extract_agui_binary(part: Any, media: AGUIUserInputMedia) -> None:
    """Route AG-UI binary input content into the matching Agno media bucket."""
    mime_type = getattr(part, "mime_type", None)
    binary_id = getattr(part, "id", None)
    url = getattr(part, "url", None)
    data = getattr(part, "data", None)
    filename = getattr(part, "filename", None)
    content = None
    data_url_mime_type = None

    if data:
        content, data_url_mime_type = _decode_agui_base64_content(data)
        if content is None:
            return

    binary_mime_type = mime_type or data_url_mime_type
    media_format = _format_from_mime_type(binary_mime_type)
    content_kwargs: Dict[str, Any]
    if url:
        content_kwargs = {"url": url}
    elif content is not None:
        content_kwargs = {"content": content}
    else:
        return

    if binary_mime_type and binary_mime_type.startswith("image/"):
        media.images.append(Image(id=binary_id, mime_type=binary_mime_type, format=media_format, **content_kwargs))
    elif binary_mime_type and binary_mime_type.startswith("audio/"):
        media.audio.append(Audio(id=binary_id, mime_type=binary_mime_type, format=media_format, **content_kwargs))
    elif binary_mime_type and binary_mime_type.startswith("video/"):
        media.videos.append(Video(id=binary_id, mime_type=binary_mime_type, format=media_format, **content_kwargs))
    else:
        media.files.append(
            File(
                id=binary_id,
                mime_type=_safe_file_mime_type(binary_mime_type),
                filename=filename,
                format=media_format,
                **content_kwargs,
            )
        )


def extract_agui_user_input_and_media(messages: List[AGUIMessage]) -> Tuple[str, AGUIUserInputMedia]:
    """Extract the last user message text and media parts from AG-UI messages.

    AG-UI frontends send the full conversation history on every request.
    The agent manages its own history via session DB, so we only need the
    latest user message as input — matching the REST API pattern.
    """
    for msg in reversed(messages):
        if msg.role == "user" and msg.content is not None:
            # UserMessage.content is Union[str, List[InputContent]]
            if isinstance(msg.content, str):
                return msg.content, AGUIUserInputMedia()
            # Multimodal: extract text and media parts
            if isinstance(msg.content, list):
                text_parts = []
                media = AGUIUserInputMedia()
                for part in msg.content:
                    part_type = getattr(part, "type", None)
                    if part_type == "text" and hasattr(part, "text"):
                        text_parts.append(part.text)
                    elif part_type == "binary":
                        _extract_agui_binary(part, media)
                    elif part_type in _AGUI_MEDIA_PARTS:
                        media_cls, field_name, sanitize = _AGUI_MEDIA_PARTS[part_type]
                        extracted = _extract_agui_media(part, media_cls, sanitize_mime=sanitize)
                        if extracted is not None:
                            getattr(media, field_name).append(extracted)
                return "\n".join(text_parts), media
    return "", AGUIUserInputMedia()


def extract_agui_user_input_and_images(messages: List[AGUIMessage]) -> Tuple[str, List[Image]]:
    """Extract the last user message text and image parts from AG-UI messages."""
    user_input, media = extract_agui_user_input_and_media(messages)
    return user_input, media.images


def extract_agui_user_input(messages: List[AGUIMessage]) -> str:
    """Extract the last user message text from AG-UI messages."""
    user_input, _ = extract_agui_user_input_and_media(messages)
    return user_input


def extract_team_response_chunk_content(response: TeamRunContentEvent) -> str:
    """Given a response stream chunk, find and extract the content."""

    # Handle Team members' responses
    members_content = []
    if hasattr(response, "member_responses") and response.member_responses:  # type: ignore
        for member_resp in response.member_responses:  # type: ignore
            if isinstance(member_resp, RunContentEvent):
                member_content = extract_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
            elif isinstance(member_resp, TeamRunContentEvent):
                member_content = extract_team_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
    members_response = "\n".join(members_content) if members_content else ""

    # Handle structured outputs
    main_content = get_text_from_message(response.content) if response.content is not None else ""

    return main_content + members_response


def extract_response_chunk_content(response: RunContentEvent) -> str:
    """Given a response stream chunk, find and extract the content."""

    if hasattr(response, "messages") and response.messages:  # type: ignore
        for msg in reversed(response.messages):  # type: ignore
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                # Handle structured outputs from messages
                return get_text_from_message(msg.content)

    # Handle structured outputs
    return get_text_from_message(response.content) if response.content is not None else ""


def _create_state_delta_events(
    run_state: Optional[Dict[str, Any]],
    event_buffer: EventBuffer,
) -> List[BaseEvent]:
    """Compute state delta and return StateDeltaEvent if state changed."""
    if run_state is None:
        return []
    ops = event_buffer.compute_state_delta(run_state)
    if ops is None:
        return []
    # Update the snapshot to current state for next delta computation
    event_buffer.set_state_snapshot(run_state)
    return [StateDeltaEvent(type=EventType.STATE_DELTA, delta=ops)]


def _format_reasoning_step_delta(step: Optional[ReasoningStep], step_number: int = 0) -> str:
    """Format a single ReasoningStep as a text delta for REASONING_MESSAGE_CONTENT.

    ReasoningStepEvent.content holds a ReasoningStep object (title, reasoning,
    action, result, confidence). We format just this one step — NOT the
    accumulated reasoning_content field, which duplicates prior steps.
    """
    if step is None:
        return ""
    parts: List[str] = []
    title = step.title or "Thinking"
    if step_number > 0:
        parts.append(f"## Step {step_number}: {title}")
    else:
        parts.append(f"## {title}")
    if step.reasoning:
        parts.append(step.reasoning)
    if step.action:
        parts.append(f"Action: {step.action}")
    if step.result:
        parts.append(f"Result: {step.result}")
    if step.confidence is not None:
        parts.append(f"Confidence: {step.confidence}")
    return "\n".join(parts) + "\n\n" if parts else ""


def _create_events_from_chunk(
    chunk: Union[RunOutputEvent, TeamRunOutputEvent],
    message_id: str,
    message_started: bool,
    event_buffer: EventBuffer,
    run_state: Optional[Dict[str, Any]] = None,
) -> Tuple[List[BaseEvent], bool, str]:
    """
    Process a single chunk and return events to emit + updated message_started state.

    Args:
        chunk: The event chunk to process
        message_id: Current message identifier
        message_started: Whether a message is currently active
        event_buffer: Event buffer for tracking tool call state (includes reasoning session state)
        run_state: Mutable dict reference to the agent's session state (for delta tracking)

    Returns:
        Tuple of (events_to_emit, new_message_started_state, message_id)
    """
    events_to_emit: List[BaseEvent] = []
    is_content_event = False

    # Extract content if the contextual event is a content event
    if chunk.event == RunEvent.run_content:
        content = extract_response_chunk_content(chunk)  # type: ignore
        is_content_event = True
    elif chunk.event == TeamRunEvent.run_content:
        content = extract_team_response_chunk_content(chunk)  # type: ignore
        is_content_event = True
    else:
        content = None

    # Handle text responses
    if content is not None:
        # Handle the message start event, emitted once per message
        if not message_started:
            message_started = True
            message_id = event_buffer.start_text_message()

            # Clear pending tool calls parent ID when starting new text message
            event_buffer.clear_pending_tool_calls_parent_id()

            start_event = TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=message_id,
                role="assistant",
            )
            events_to_emit.append(start_event)

        # Handle the text content event, emitted once per text chunk
        if content is not None and content != "":
            content_event = TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=content,
            )
            events_to_emit.append(content_event)  # type: ignore

    # Handle starting a new tool
    elif chunk.event == RunEvent.tool_call_started or chunk.event == TeamRunEvent.tool_call_started:
        if chunk.tool is not None:  # type: ignore
            tool_call = chunk.tool  # type: ignore

            # End current text message and handle for tool calls
            current_message_id = message_id
            if message_started:
                # End the current text message
                end_message_event = TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=current_message_id)
                events_to_emit.append(end_message_event)

                # Set this message as the parent for any upcoming tool calls
                # This ensures multiple sequential tool calls all use the same parent
                event_buffer.set_pending_tool_calls_parent_id(current_message_id)

                # Reset message started state and generate new message_id for future messages
                message_started = False
                message_id = str(uuid.uuid4())

            # Get the parent message ID - this will use pending parent if set, ensuring multiple tool calls in sequence have the same parent
            parent_message_id = event_buffer.get_parent_message_id_for_tool_call()

            if not parent_message_id:
                # Create parent message for tool calls without preceding assistant message
                parent_message_id = str(uuid.uuid4())

                # Emit a text message to serve as the parent
                text_start = TextMessageStartEvent(
                    type=EventType.TEXT_MESSAGE_START,
                    message_id=parent_message_id,
                    role="assistant",
                )
                events_to_emit.append(text_start)

                text_end = TextMessageEndEvent(
                    type=EventType.TEXT_MESSAGE_END,
                    message_id=parent_message_id,
                )
                events_to_emit.append(text_end)

                # Set this as the pending parent for subsequent tool calls in this batch
                event_buffer.set_pending_tool_calls_parent_id(parent_message_id)

            start_event = ToolCallStartEvent(
                type=EventType.TOOL_CALL_START,
                tool_call_id=tool_call.tool_call_id,  # type: ignore
                tool_call_name=tool_call.tool_name,  # type: ignore
                parent_message_id=parent_message_id,
            )
            events_to_emit.append(start_event)

            args_event = ToolCallArgsEvent(
                type=EventType.TOOL_CALL_ARGS,
                tool_call_id=tool_call.tool_call_id,  # type: ignore
                delta=json.dumps(tool_call.tool_args),
            )
            events_to_emit.append(args_event)  # type: ignore

    # Handle tool call completion
    elif chunk.event == RunEvent.tool_call_completed or chunk.event == TeamRunEvent.tool_call_completed:
        if chunk.tool is not None:  # type: ignore
            tool_call = chunk.tool  # type: ignore
            if tool_call.tool_call_id not in event_buffer.ended_tool_call_ids:
                end_event = ToolCallEndEvent(
                    type=EventType.TOOL_CALL_END,
                    tool_call_id=tool_call.tool_call_id,  # type: ignore
                )
                events_to_emit.append(end_event)

                if tool_call.result is not None:
                    result_event = ToolCallResultEvent(
                        type=EventType.TOOL_CALL_RESULT,
                        tool_call_id=tool_call.tool_call_id,  # type: ignore
                        content=str(tool_call.result),
                        role="tool",
                        message_id=str(uuid.uuid4()),
                    )
                    events_to_emit.append(result_event)

                # Emit state delta after tool call completion (state may have been mutated by the tool)
                events_to_emit.extend(_create_state_delta_events(run_state, event_buffer))

    # Handle reasoning — isinstance() dispatch for Agent and Team event types.
    # Two producers: native model reasoning (o4-mini, Claude extended thinking)
    # emits ReasoningContentDeltaEvent with true streaming deltas, while
    # ReasoningTools (think/analyze) emits ReasoningStepEvent with a ReasoningStep object.
    elif isinstance(chunk, (AgentReasoningStartedEvent, TeamReasoningStartedEvent)):
        reasoning_id = event_buffer.start_reasoning()
        events_to_emit.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
        events_to_emit.append(
            ReasoningMessageStartEvent(
                type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"
            )
        )

    elif isinstance(chunk, (AgentReasoningContentDeltaEvent, TeamReasoningContentDeltaEvent)):
        # Native model reasoning — chunk.reasoning_content is a true streaming delta
        reasoning_id, is_new = event_buffer.ensure_reasoning_started()
        if is_new:
            events_to_emit.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
            events_to_emit.append(
                ReasoningMessageStartEvent(
                    type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"
                )
            )
        if chunk.reasoning_content:
            events_to_emit.append(
                ReasoningMessageContentEvent(
                    type=EventType.REASONING_MESSAGE_CONTENT, message_id=reasoning_id, delta=chunk.reasoning_content
                )
            )

    elif isinstance(chunk, (AgentReasoningStepEvent, TeamReasoningStepEvent)):
        # ReasoningTools — chunk.reasoning_content is accumulated (all steps so far),
        # so we format chunk.content (the single ReasoningStep) as the delta instead
        reasoning_id, is_new = event_buffer.ensure_reasoning_started()
        if is_new:
            events_to_emit.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
            events_to_emit.append(
                ReasoningMessageStartEvent(
                    type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"
                )
            )
        step_num = event_buffer.next_reasoning_step()
        delta = _format_reasoning_step_delta(chunk.content, step_num)
        if delta:
            events_to_emit.append(
                ReasoningMessageContentEvent(
                    type=EventType.REASONING_MESSAGE_CONTENT, message_id=reasoning_id, delta=delta
                )
            )

    elif isinstance(chunk, (AgentReasoningCompletedEvent, TeamReasoningCompletedEvent)):
        if event_buffer.reasoning_message_id is not None:
            reasoning_id = event_buffer.reasoning_message_id
            events_to_emit.append(
                ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=reasoning_id)
            )
            events_to_emit.append(ReasoningEndEvent(type=EventType.REASONING_END, message_id=reasoning_id))
            event_buffer.end_reasoning()

    # Handle custom events
    elif chunk.event in (RunEvent.custom_event, TeamRunEvent.custom_event):
        # Use the name of the event class if available, otherwise default to the CustomEvent
        try:
            custom_event_name = chunk.__class__.__name__
        except Exception:
            custom_event_name = chunk.event

        # Use the complete Agno event as value if parsing it works, else the event content field
        try:
            custom_event_value = chunk.to_dict()
        except Exception:
            custom_event_value = chunk.content  # type: ignore

        custom_event = CustomEvent(name=custom_event_name, value=custom_event_value)
        events_to_emit.append(custom_event)

    # Catch-all: emit unmapped events as RawEvent (skip content events which may have None content)
    elif not is_content_event:
        try:
            raw_dict = chunk.to_dict()
        except Exception:
            raw_dict = {"event": str(chunk.event)}
        events_to_emit.append(RawEvent(type=EventType.RAW, event=raw_dict, source="agno"))

    return events_to_emit, message_started, message_id


def _create_completion_events(
    chunk: Union[RunOutputEvent, TeamRunOutputEvent],
    event_buffer: EventBuffer,
    message_started: bool,
    message_id: str,
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
) -> List[BaseEvent]:
    """Create events for run completion."""
    events_to_emit: List[BaseEvent] = []

    # Close orphaned reasoning session if stream ended mid-reasoning
    if event_buffer.reasoning_message_id is not None:
        events_to_emit.append(
            ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=event_buffer.reasoning_message_id)
        )
        events_to_emit.append(
            ReasoningEndEvent(type=EventType.REASONING_END, message_id=event_buffer.reasoning_message_id)
        )
        event_buffer.end_reasoning()

    # End remaining active tool calls if needed
    for tool_call_id in list(event_buffer.active_tool_call_ids):
        if tool_call_id not in event_buffer.ended_tool_call_ids:
            end_event = ToolCallEndEvent(
                type=EventType.TOOL_CALL_END,
                tool_call_id=tool_call_id,
            )
            events_to_emit.append(end_event)

    # End the message and run, denoting the end of the session
    if message_started:
        end_message_event = TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id)
        events_to_emit.append(end_message_event)

    # Emit external execution tools
    if isinstance(chunk, RunPausedEvent):
        external_tools = chunk.tools_awaiting_external_execution
        if external_tools:
            # First, emit an assistant message for external tool calls
            assistant_message_id = str(uuid.uuid4())
            assistant_start_event = TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=assistant_message_id,
                role="assistant",
            )
            events_to_emit.append(assistant_start_event)

            # Add any text content if present for the assistant message
            if chunk.content:
                content_event = TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=assistant_message_id,
                    delta=str(chunk.content),
                )
                events_to_emit.append(content_event)

            # End the assistant message
            assistant_end_event = TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=assistant_message_id,
            )
            events_to_emit.append(assistant_end_event)

            # Emit tool call events for external execution
            for tool in external_tools:
                if tool.tool_call_id is None or tool.tool_name is None:
                    continue

                start_event = ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool.tool_call_id,
                    tool_call_name=tool.tool_name,
                    parent_message_id=assistant_message_id,  # Use the assistant message as parent
                )
                events_to_emit.append(start_event)

                args_event = ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool.tool_call_id,
                    delta=json.dumps(tool.tool_args),
                )
                events_to_emit.append(args_event)

                end_event = ToolCallEndEvent(
                    type=EventType.TOOL_CALL_END,
                    tool_call_id=tool.tool_call_id,
                )
                events_to_emit.append(end_event)

    # Emit final state snapshot before finishing the run (only if frontend opted into state tracking)
    if run_state is not None:
        # Use session_state from RunCompletedEvent (authoritative) if available, otherwise fall back to run_state.
        # Deep-copy so the emitted event doesn't alias the live agent state (consistent with set_state_snapshot).
        authoritative_state = getattr(chunk, "session_state", None)
        final_state = authoritative_state if authoritative_state is not None else run_state
        snapshot_event = StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(final_state))
        events_to_emit.append(snapshot_event)

    run_finished_event = RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id)
    events_to_emit.append(run_finished_event)

    return events_to_emit


def _emit_event_logic(event: BaseEvent, event_buffer: EventBuffer) -> List[BaseEvent]:
    """Process an event and return events to actually emit."""
    events_to_emit: List[BaseEvent] = [event]

    # Update the event buffer state for tracking purposes
    if event.type == EventType.TOOL_CALL_START:
        tool_call_id = getattr(event, "tool_call_id", None)
        if tool_call_id:
            event_buffer.start_tool_call(tool_call_id)
    elif event.type == EventType.TOOL_CALL_END:
        tool_call_id = getattr(event, "tool_call_id", None)
        if tool_call_id:
            event_buffer.end_tool_call(tool_call_id)

    return events_to_emit


def stream_agno_response_as_agui_events(
    response_stream: Iterator[Union[RunOutputEvent, TeamRunOutputEvent]],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
) -> Iterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format, handling event ordering constraints."""
    message_id = ""  # Will be set by EventBuffer when text message starts
    message_started = False
    event_buffer = EventBuffer()
    stream_completed = False

    # Establish baseline state snapshot for delta tracking
    if run_state is not None:
        event_buffer.set_state_snapshot(run_state)

    completion_chunk = None

    for chunk in response_stream:
        # Check if this is a completion event
        if (
            chunk.event == RunEvent.run_completed
            or chunk.event == TeamRunEvent.run_completed
            or chunk.event == RunEvent.run_paused
            or chunk.event == TeamRunEvent.run_paused
        ):
            # Store completion chunk but don't process it yet
            completion_chunk = chunk
            stream_completed = True
        else:
            # Process regular chunk immediately
            events_from_chunk, message_started, message_id = _create_events_from_chunk(
                chunk, message_id, message_started, event_buffer, run_state=run_state
            )

            for event in events_from_chunk:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event

    # Process ONLY completion cleanup events, not content from completion chunk
    if completion_chunk:
        completion_events = _create_completion_events(
            completion_chunk, event_buffer, message_started, message_id, thread_id, run_id, run_state=run_state
        )
        for event in completion_events:
            events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
            for emit_event in events_to_emit:
                yield emit_event

    # Ensure completion events are always emitted even when stream ends naturally
    if not stream_completed:
        # Create a synthetic completion event to ensure proper cleanup
        from agno.run.agent import RunCompletedEvent

        synthetic_completion = RunCompletedEvent()
        completion_events = _create_completion_events(
            synthetic_completion, event_buffer, message_started, message_id, thread_id, run_id, run_state=run_state
        )
        for event in completion_events:
            events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
            for emit_event in events_to_emit:
                yield emit_event


# Async version - thin wrapper
async def async_stream_agno_response_as_agui_events(
    response_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format, handling event ordering constraints."""
    message_id = ""  # Will be set by EventBuffer when text message starts
    message_started = False
    event_buffer = EventBuffer()
    stream_completed = False

    # Establish baseline state snapshot for delta tracking
    if run_state is not None:
        event_buffer.set_state_snapshot(run_state)

    completion_chunk = None

    async for chunk in response_stream:
        # Check if this is a completion event
        if (
            chunk.event == RunEvent.run_completed
            or chunk.event == TeamRunEvent.run_completed
            or chunk.event == RunEvent.run_paused
            or chunk.event == TeamRunEvent.run_paused
        ):
            # Store completion chunk but don't process it yet
            completion_chunk = chunk
            stream_completed = True
        else:
            # Process regular chunk immediately
            events_from_chunk, message_started, message_id = _create_events_from_chunk(
                chunk, message_id, message_started, event_buffer, run_state=run_state
            )

            for event in events_from_chunk:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event

    # Process ONLY completion cleanup events, not content from completion chunk
    if completion_chunk:
        completion_events = _create_completion_events(
            completion_chunk, event_buffer, message_started, message_id, thread_id, run_id, run_state=run_state
        )
        for event in completion_events:
            events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
            for emit_event in events_to_emit:
                yield emit_event

    # Ensure completion events are always emitted even when stream ends naturally
    if not stream_completed:
        # Create a synthetic completion event to ensure proper cleanup
        from agno.run.agent import RunCompletedEvent

        synthetic_completion = RunCompletedEvent()
        completion_events = _create_completion_events(
            synthetic_completion, event_buffer, message_started, message_id, thread_id, run_id, run_state=run_state
        )
        for event in completion_events:
            events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
            for emit_event in events_to_emit:
                yield emit_event
