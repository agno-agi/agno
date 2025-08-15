"""Logic used by the AG-UI router."""

import json
import uuid
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import AsyncIterator, Deque, List, Optional, Set, Tuple, Union

from ag_ui.core import (
    BaseEvent,
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

from agno.models.message import Message
from agno.run.response import RunEvent, RunResponseContentEvent, RunResponseEvent, RunResponsePausedEvent
from agno.run.team import RunResponseContentEvent as TeamRunResponseContentEvent
from agno.run.team import TeamRunEvent, TeamRunResponseEvent


@dataclass
class EventBuffer:
    """Buffer to manage event ordering constraints, relevant when mapping Agno responses to AG-UI events."""

    buffer: Deque[BaseEvent]
    blocking_tool_call_id: Optional[str]  # The tool call that's currently blocking the buffer
    active_tool_call_ids: Set[str]  # All currently active tool calls
    ended_tool_call_ids: Set[str]  # All tool calls that have ended

    def __init__(self):
        self.buffer = deque()
        self.blocking_tool_call_id = None
        self.active_tool_call_ids = set()
        self.ended_tool_call_ids = set()

    def is_blocked(self) -> bool:
        """Check if the buffer is currently blocked by an active tool call."""
        return self.blocking_tool_call_id is not None

    def start_tool_call(self, tool_call_id: str) -> None:
        """Start a new tool call, marking it the current blocking tool call if needed."""
        self.active_tool_call_ids.add(tool_call_id)
        if self.blocking_tool_call_id is None:
            self.blocking_tool_call_id = tool_call_id

    def end_tool_call(self, tool_call_id: str) -> bool:
        """End a tool call, marking it as ended and updating the blocking state.
        
        When the currently blocking tool call ends, automatically select the next
        active tool call as the new blocking tool call. This prevents inconsistent
        states when multiple concurrent tool calls are active, which could lead to
        infinite loops in event processing.
        
        Args:
            tool_call_id: The ID of the tool call that is ending
            
        Returns:
            True if this tool call was the blocking one (and thus unblocked the buffer),
            False otherwise
        """
        self.active_tool_call_ids.discard(tool_call_id)
        self.ended_tool_call_ids.add(tool_call_id)

        # Update blocking state if the current blocking tool call is ending
        if tool_call_id == self.blocking_tool_call_id:
            # Select next active tool call as blocking, if any
            # This ensures proper state management with multiple concurrent tool calls
            if self.active_tool_call_ids:
                self.blocking_tool_call_id = next(iter(self.active_tool_call_ids))
            else:
                self.blocking_tool_call_id = None
            return True

        return False


def convert_agui_messages_to_agno_messages(messages: List[AGUIMessage]) -> List[Message]:
    """Convert AG-UI messages to Agno messages."""
    result = []
    for msg in messages:
        if msg.role == "tool":
            result.append(Message(role="tool", tool_call_id=msg.tool_call_id, content=msg.content))
        elif msg.role == "assistant":
            tool_calls = None
            if msg.tool_calls:
                tool_calls = [call.model_dump() for call in msg.tool_calls]
            result.append(
                Message(
                    role="assistant",
                    content=msg.content,
                    tool_calls=tool_calls,
                )
            )
        elif msg.role == "user":
            result.append(Message(role="user", content=msg.content))
    return result


def extract_team_response_chunk_content(response: TeamRunResponseContentEvent) -> str:
    """Given a response stream chunk, find and extract the content."""

    # Handle Team members' responses
    members_content = []
    if hasattr(response, "member_responses") and response.member_responses:  # type: ignore
        for member_resp in response.member_responses:  # type: ignore
            if isinstance(member_resp, RunResponseContentEvent):
                member_content = extract_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
            elif isinstance(member_resp, TeamRunResponseContentEvent):
                member_content = extract_team_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
    members_response = "\n".join(members_content) if members_content else ""

    return str(response.content) + members_response


def extract_response_chunk_content(response: RunResponseContentEvent) -> str:
    """Given a response stream chunk, find and extract the content."""
    if hasattr(response, "messages") and response.messages:  # type: ignore
        for msg in reversed(response.messages):  # type: ignore
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                return str(msg.content)

    return str(response.content) if response.content else ""


def _create_events_from_chunk(
    chunk: Union[RunResponseEvent, TeamRunResponseEvent],
    message_id: str,
    message_started: bool,
    event_buffer: EventBuffer,
) -> Tuple[List[BaseEvent], bool]:
    """
    Process a single chunk and return events to emit + updated message_started state.
    Returns: (events_to_emit, new_message_started_state)
    """
    events_to_emit: List[BaseEvent] = []

    # Extract content if the contextual event is a content event
    if chunk.event == RunEvent.run_response_content:
        content = extract_response_chunk_content(chunk)  # type: ignore
    elif chunk.event == TeamRunEvent.run_response_content:
        content = extract_team_response_chunk_content(chunk)  # type: ignore
    elif chunk.event == RunEvent.run_error:
        # Extract error content directly from the chunk
        content = getattr(chunk, 'content', None) or str(chunk)
    else:
        content = None

    # Handle text responses
    if content is not None:
        # Handle the message start event, emitted once per message
        if not message_started:
            message_started = True
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
            events_to_emit.append(content_event)

    # Handle starting a new tool call
    elif chunk.event == RunEvent.tool_call_started:
        if chunk.tool is not None:  # type: ignore
            tool_call = chunk.tool  # type: ignore
            start_event = ToolCallStartEvent(
                type=EventType.TOOL_CALL_START,
                tool_call_id=tool_call.tool_call_id,  # type: ignore
                tool_call_name=tool_call.tool_name,  # type: ignore
                parent_message_id=message_id,
            )
            events_to_emit.append(start_event)

            args_event = ToolCallArgsEvent(
                type=EventType.TOOL_CALL_ARGS,
                tool_call_id=tool_call.tool_call_id,  # type: ignore
                delta=json.dumps(tool_call.tool_args),
            )
            events_to_emit.append(args_event)

    # Handle tool call completion
    elif chunk.event == RunEvent.tool_call_completed:
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
        step_event = StepStartedEvent(type=EventType.STEP_STARTED, step_name="reasoning")
        events_to_emit.append(step_event)
    elif chunk.event == RunEvent.reasoning_completed:
        step_finished_event = StepFinishedEvent(type=EventType.STEP_FINISHED, step_name="reasoning")
        events_to_emit.append(step_finished_event)

    return events_to_emit, message_started


def _create_completion_events(
    chunk: Union[RunResponseEvent, TeamRunResponseEvent],
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

    # emit frontend tool calls, i.e. external_execution=True
    if isinstance(chunk, RunResponsePausedEvent) and chunk.tools is not None:
        for tool in chunk.tools:
            if tool.tool_call_id is None or tool.tool_name is None:
                continue

            start_event = ToolCallStartEvent(
                type=EventType.TOOL_CALL_START,
                tool_call_id=tool.tool_call_id,
                tool_call_name=tool.tool_name,
                parent_message_id=message_id,
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
    """Process an event through the buffer and return events to actually emit.
    
    This function handles event ordering constraints for AG-UI integration, particularly
    around tool call blocking behavior. It uses an iterative queue-based approach to
    avoid recursion issues that can occur with multiple concurrent tool calls.
    
    Key behaviors:
    - Tool calls are processed sequentially to maintain UI consistency
    - Only one tool call can be "blocking" at a time 
    - Events for non-blocking tool calls are buffered until the blocking tool call completes
    - When a blocking tool call ends, buffered events are processed in order
    """
    events_to_emit: List[BaseEvent] = []
    events_to_process = [event]  # Use a queue instead of recursion to prevent infinite loops
    
    while events_to_process:
        current_event = events_to_process.pop(0)
        
        if event_buffer.is_blocked():
            # Buffer is currently blocked by an active tool call
            if current_event.type == EventType.TOOL_CALL_ARGS:
                # Allow TOOL_CALL_ARGS events for the active tool call to pass through
                if hasattr(current_event, "tool_call_id") and current_event.tool_call_id in event_buffer.active_tool_call_ids:  # type: ignore
                    events_to_emit.append(current_event)
                else:
                    event_buffer.buffer.append(current_event)
            elif current_event.type == EventType.TOOL_CALL_END:
                tool_call_id = getattr(current_event, "tool_call_id", None)
                if tool_call_id and tool_call_id == event_buffer.blocking_tool_call_id:
                    # The blocking tool call is ending - emit the event and process buffered events
                    events_to_emit.append(current_event)
                    event_buffer.end_tool_call(tool_call_id)
                    
                    # Process all buffered events now that the blocking tool call has ended
                    # Add them to the processing queue rather than recursively calling this function
                    while event_buffer.buffer:
                        buffered_event = event_buffer.buffer.popleft()
                        events_to_process.append(buffered_event)
                elif tool_call_id and tool_call_id in event_buffer.active_tool_call_ids:
                    # A non-blocking tool call is ending - buffer the event and update state
                    event_buffer.buffer.append(current_event)
                    event_buffer.end_tool_call(tool_call_id)
                else:
                    # Unrelated tool call ending - just buffer it
                    event_buffer.buffer.append(current_event)
            else:
                # All other events get buffered while blocking
                event_buffer.buffer.append(current_event)
        else:
            # Buffer is not blocked - emit events normally
            if current_event.type == EventType.TOOL_CALL_START:
                tool_call_id = getattr(current_event, "tool_call_id", None)
                if tool_call_id:
                    event_buffer.start_tool_call(tool_call_id)
                events_to_emit.append(current_event)
            elif current_event.type == EventType.TOOL_CALL_END:
                tool_call_id = getattr(current_event, "tool_call_id", None)
                if tool_call_id:
                    event_buffer.end_tool_call(tool_call_id)
                events_to_emit.append(current_event)
            else:
                events_to_emit.append(current_event)

    return events_to_emit


def stream_agno_response_as_agui_events(
    response_stream: Iterator[Union[RunResponseEvent, TeamRunResponseEvent]], thread_id: str, run_id: str
) -> Iterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format, handling event ordering constraints."""
    message_id = str(uuid.uuid4())
    message_started = False
    event_buffer = EventBuffer()

    for chunk in response_stream:
        # Handle error events - process content first, then trigger completion
        if chunk.event == RunEvent.run_error:
            # Process error content as a text message
            events_from_chunk, message_started = _create_events_from_chunk(
                chunk, message_id, message_started, event_buffer
            )
            for event in events_from_chunk:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event
            
            # Then trigger completion
            completion_events = _create_completion_events(
                chunk, event_buffer, message_started, message_id, thread_id, run_id
            )
            for event in completion_events:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event
        # Handle other lifecycle end events
        elif (
            chunk.event == RunEvent.run_completed
            or chunk.event == TeamRunEvent.run_completed
            or chunk.event == RunEvent.run_paused
        ):
            completion_events = _create_completion_events(
                chunk, event_buffer, message_started, message_id, thread_id, run_id
            )
            for event in completion_events:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event
        else:
            # Process regular chunk
            events_from_chunk, message_started = _create_events_from_chunk(
                chunk, message_id, message_started, event_buffer
            )

            for event in events_from_chunk:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event


# Async version - thin wrapper
async def async_stream_agno_response_as_agui_events(
    response_stream: AsyncIterator[Union[RunResponseEvent, TeamRunResponseEvent]],
    thread_id: str,
    run_id: str,
) -> AsyncIterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format, handling event ordering constraints."""
    message_id = str(uuid.uuid4())
    message_started = False
    event_buffer = EventBuffer()

    last_chunk = None
    async for chunk in response_stream:
        last_chunk = chunk
        # Handle error events - process content first, then trigger completion
        if chunk.event == RunEvent.run_error:
            # Process error content as a text message
            events_from_chunk, message_started = _create_events_from_chunk(
                chunk, message_id, message_started, event_buffer
            )
            for event in events_from_chunk:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event
            
            # Then trigger completion
            completion_events = _create_completion_events(
                chunk, event_buffer, message_started, message_id, thread_id, run_id
            )
            for event in completion_events:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event
        # Handle other lifecycle end events
        elif (
            chunk.event == RunEvent.run_completed
            or chunk.event == TeamRunEvent.run_completed
            or chunk.event == RunEvent.run_paused
        ):
            completion_events = _create_completion_events(
                chunk, event_buffer, message_started, message_id, thread_id, run_id
            )
            for event in completion_events:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event
        else:
            # Process regular chunk
            events_from_chunk, message_started = _create_events_from_chunk(
                chunk, message_id, message_started, event_buffer
            )

            for event in events_from_chunk:
                events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
                for emit_event in events_to_emit:
                    yield emit_event

    # Handle natural stream end - emit completion events if no explicit completion was received
    if last_chunk and last_chunk.event not in [
        RunEvent.run_completed,
        TeamRunEvent.run_completed,
        RunEvent.run_paused,
        RunEvent.run_error,
    ]:
        # Create a synthetic completion event
        synthetic_completion = RunResponseContentEvent()
        synthetic_completion.event = RunEvent.run_completed
        synthetic_completion.content = ""
        
        completion_events = _create_completion_events(
            synthetic_completion, event_buffer, message_started, message_id, thread_id, run_id
        )
        for event in completion_events:
            events_to_emit = _emit_event_logic(event_buffer=event_buffer, event=event)
            for emit_event in events_to_emit:
                yield emit_event
