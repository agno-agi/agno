"""Logic used by the AG-UI router."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple, Union

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    RunFinishedEvent,
    StepFinishedEvent,
    StepStartedEvent,
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

from agno.models.message import Message
from agno.run.agent import RunContentEvent, RunEvent, RunOutputEvent, RunPausedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import TeamRunEvent, TeamRunOutputEvent
from agno.utils.log import log_debug, log_warning
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

    def __init__(self):
        self.active_tool_call_ids = set()
        self.ended_tool_call_ids = set()
        self.current_text_message_id = ""
        self.next_text_message_id = str(uuid.uuid4())
        self.pending_tool_calls_parent_id = ""

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


def convert_agui_messages_to_agno_messages(messages: List[AGUIMessage]) -> List[Message]:
    """Convert AG-UI messages to Agno messages."""
    # First pass: collect all tool_call_ids that have results
    tool_call_ids_with_results: Set[str] = set()
    for msg in messages:
        if msg.role == "tool" and msg.tool_call_id:
            tool_call_ids_with_results.add(msg.tool_call_id)

    # Second pass: convert messages
    result: List[Message] = []
    seen_tool_call_ids: Set[str] = set()

    for msg in messages:
        if msg.role == "tool":
            # Deduplicate tool results - keep only first occurrence
            if msg.tool_call_id in seen_tool_call_ids:
                log_debug(f"Skipping duplicate AGUI tool result: {msg.tool_call_id}")
                continue
            seen_tool_call_ids.add(msg.tool_call_id)
            result.append(Message(role="tool", tool_call_id=msg.tool_call_id, content=msg.content))

        elif msg.role == "assistant":
            tool_calls = None
            if msg.tool_calls:
                # Filter tool_calls to only those with results in this message sequence
                filtered_calls = [call for call in msg.tool_calls if call.id in tool_call_ids_with_results]
                if filtered_calls:
                    tool_calls = [call.model_dump() for call in filtered_calls]
            result.append(Message(role="assistant", content=msg.content, tool_calls=tool_calls))

        elif msg.role == "user":
            result.append(Message(role="user", content=msg.content))

        elif msg.role == "system":
            pass  # Skip - agent builds its own system message from configuration

        else:
            log_warning(f"Unknown AGUI message role: {msg.role}")

    return result


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


def _create_events_from_chunk(
    chunk: Union[RunOutputEvent, TeamRunOutputEvent],
    message_id: str,
    message_started: bool,
    event_buffer: EventBuffer,
) -> Tuple[List[BaseEvent], bool, str]:
    """
    Process a single chunk and return events to emit + updated message_started state.

    Args:
        chunk: The event chunk to process
        message_id: Current message identifier
        message_started: Whether a message is currently active
        event_buffer: Event buffer for tracking tool call state

    Returns:
        Tuple of (events_to_emit, new_message_started_state, message_id)
    """
    events_to_emit: List[BaseEvent] = []

    # Extract content if the contextual event is a content event
    if chunk.event == RunEvent.run_content:
        content = extract_response_chunk_content(chunk)  # type: ignore
    elif chunk.event == TeamRunEvent.run_content:
        content = extract_team_response_chunk_content(chunk)  # type: ignore
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

    # Handle reasoning
    elif chunk.event == RunEvent.reasoning_started:
        step_started_event = StepStartedEvent(type=EventType.STEP_STARTED, step_name="reasoning")
        events_to_emit.append(step_started_event)
    elif chunk.event == RunEvent.reasoning_completed:
        step_finished_event = StepFinishedEvent(type=EventType.STEP_FINISHED, step_name="reasoning")
        events_to_emit.append(step_finished_event)

    # Handle custom events
    elif chunk.event == RunEvent.custom_event:
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

    return events_to_emit, message_started, message_id


def _create_completion_events(
    chunk: Union[RunOutputEvent, TeamRunOutputEvent],
    event_buffer: EventBuffer,
    message_started: bool,
    message_id: str,
    thread_id: str,
    run_id: str,
) -> List[BaseEvent]:
    """Create events for run completion."""
    events_to_emit: List[BaseEvent] = []

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
    response_stream: Iterator[Union[RunOutputEvent, TeamRunOutputEvent]], thread_id: str, run_id: str
) -> Iterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format, handling event ordering constraints."""
    message_id = ""  # Will be set by EventBuffer when text message starts
    message_started = False
    event_buffer = EventBuffer()
    stream_completed = False

    completion_chunk = None

    for chunk in response_stream:
        # Check if this is a completion event
        if (
            chunk.event == RunEvent.run_completed
            or chunk.event == TeamRunEvent.run_completed
            or chunk.event == RunEvent.run_paused
        ):
            # Store completion chunk but don't process it yet
            completion_chunk = chunk
            stream_completed = True
        else:
            # Process regular chunk immediately
            events_from_chunk, message_started, message_id = _create_events_from_chunk(
                chunk, message_id, message_started, event_buffer
            )

            for event in events_from_chunk:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event

    # Process ONLY completion cleanup events, not content from completion chunk
    if completion_chunk:
        completion_events = _create_completion_events(
            completion_chunk, event_buffer, message_started, message_id, thread_id, run_id
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
            synthetic_completion, event_buffer, message_started, message_id, thread_id, run_id
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
) -> AsyncIterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format, handling event ordering constraints."""
    message_id = ""  # Will be set by EventBuffer when text message starts
    message_started = False
    event_buffer = EventBuffer()
    stream_completed = False

    completion_chunk = None

    async for chunk in response_stream:
        # Check if this is a completion event
        if (
            chunk.event == RunEvent.run_completed
            or chunk.event == TeamRunEvent.run_completed
            or chunk.event == RunEvent.run_paused
        ):
            # Store completion chunk but don't process it yet
            completion_chunk = chunk
            stream_completed = True
        else:
            # Process regular chunk immediately
            events_from_chunk, message_started, message_id = _create_events_from_chunk(
                chunk, message_id, message_started, event_buffer
            )

            for event in events_from_chunk:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event

    # Process ONLY completion cleanup events, not content from completion chunk
    if completion_chunk:
        completion_events = _create_completion_events(
            completion_chunk, event_buffer, message_started, message_id, thread_id, run_id
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
            synthetic_completion, event_buffer, message_started, message_id, thread_id, run_id
        )
        for event in completion_events:
            events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
            for emit_event in events_to_emit:
                yield emit_event
