"""Logic used by the AG-UI router."""

import uuid
from collections import deque
from dataclasses import dataclass
from typing import AsyncIterator, Deque, List, Optional, Set, Union

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
    ToolCallStartEvent,
)
from ag_ui.core.types import Message as AGUIMessage

from agno.run.response import RunEvent, RunResponse
from agno.run.team import TeamRunResponse


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
        """End a tool call, marking it as ended and unblocking the buffer if needed."""
        self.active_tool_call_ids.discard(tool_call_id)
        self.ended_tool_call_ids.add(tool_call_id)

        # Unblock the buffer if the current blocking tool call is the one ending
        if tool_call_id == self.blocking_tool_call_id:
            self.blocking_tool_call_id = None
            return True

        return False


def get_last_user_message(messages: Optional[List[AGUIMessage]]) -> str:
    if not messages:
        return ""
    for msg in reversed(messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return ""


def extract_team_response_chunk_content(response: TeamRunResponse) -> str:
    """Given a response stream chunk, find and extract the content."""

    # Handle Team members' responses
    members_content = []
    if hasattr(response, "member_responses") and response.member_responses:
        for member_resp in response.member_responses:
            if isinstance(member_resp, RunResponse):
                member_content = extract_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
            elif isinstance(member_resp, TeamRunResponse):
                member_content = extract_team_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
    members_response = "\n".join(members_content) if members_content else ""

    return str(response.content) + members_response


def extract_response_chunk_content(response: RunResponse) -> str:
    """Given a response stream chunk, find and extract the content."""
    if hasattr(response, "messages") and response.messages:
        for msg in reversed(response.messages):
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                return str(msg.content)

    return str(response.content) if response.content else ""


async def stream_agno_response_as_agui_events(
    response_stream: Union[AsyncIterator[RunResponse], AsyncIterator[TeamRunResponse]], thread_id: str, run_id: str
) -> AsyncIterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format, handling event ordering constraints."""
    message_id = str(uuid.uuid4())
    message_started = False
    event_buffer = EventBuffer()

    async def emit_event(event: BaseEvent) -> AsyncIterator[BaseEvent]:
        """Emit an event, respecting event ordering constraints."""
        if event_buffer.is_blocked():
            # Handle events related to the current blocking tool call
            if event.type == EventType.TOOL_CALL_ARGS:
                if hasattr(event, "tool_call_id") and event.tool_call_id in event_buffer.active_tool_call_ids:  # type: ignore
                    yield event
                else:
                    event_buffer.buffer.append(event)
            elif event.type == EventType.TOOL_CALL_END:
                tool_call_id = getattr(event, "tool_call_id", None)
                if tool_call_id and tool_call_id == event_buffer.blocking_tool_call_id:
                    yield event
                    event_buffer.end_tool_call(tool_call_id)
                    # Flush buffered events after ending the blocking tool call
                    while event_buffer.buffer:
                        buffered_event = event_buffer.buffer.popleft()
                        # Recursively process buffered events in case they contain blocking tool calls
                        async for nested_event in emit_event(buffered_event):
                            yield nested_event
                elif tool_call_id and tool_call_id in event_buffer.active_tool_call_ids:
                    event_buffer.buffer.append(event)
                    event_buffer.end_tool_call(tool_call_id)
                else:
                    event_buffer.buffer.append(event)

            # Handle all other events
            elif event.type == EventType.TOOL_CALL_START:
                event_buffer.buffer.append(event)
            else:
                event_buffer.buffer.append(event)

        # If the buffer is not blocked, emit the events normally
        else:
            if event.type == EventType.TOOL_CALL_START:
                tool_call_id = getattr(event, "tool_call_id", None)
                if tool_call_id:
                    event_buffer.start_tool_call(tool_call_id)
                yield event
            elif event.type == EventType.TOOL_CALL_END:
                tool_call_id = getattr(event, "tool_call_id", None)
                if tool_call_id:
                    event_buffer.end_tool_call(tool_call_id)
                yield event
            else:
                yield event

    async for chunk in response_stream:
        if isinstance(chunk, RunResponse):
            content = extract_response_chunk_content(chunk)
        elif isinstance(chunk, TeamRunResponse):
            content = extract_team_response_chunk_content(chunk)

        # Handle text responses
        if chunk.event == RunEvent.run_response:
            # Handle the message start event, emitted once per message
            if not message_started:
                message_started = True
                start_event = TextMessageStartEvent(
                    type=EventType.TEXT_MESSAGE_START,
                    message_id=message_id,
                    role="assistant",
                )
                async for event in emit_event(start_event):
                    yield event
            # Handle the text content event, emitted once per text chunk
            if content is not None and content != "":
                content_event = TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=message_id,
                    delta=content,
                )
                async for event in emit_event(content_event):
                    yield event

        # Handle starting a new tool call
        elif chunk.event == RunEvent.tool_call_started:
            if chunk.tools is not None and len(chunk.tools) != 0:
                tool_call = chunk.tools[0]
                start_event = ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool_call.tool_call_id,  # type: ignore
                    tool_call_name=tool_call.tool_name,  # type: ignore
                    parent_message_id=message_id,
                )
                async for event in emit_event(start_event):
                    yield event
                args_event = ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool_call.tool_call_id,  # type: ignore
                    delta=str(tool_call.tool_args),
                )
                async for event in emit_event(args_event):
                    yield event

        # Handle tool call completion
        elif chunk.event == RunEvent.tool_call_completed:
            if chunk.tools is not None and len(chunk.tools) != 0:
                tool_call = chunk.tools[0]
                if tool_call.tool_call_id not in event_buffer.ended_tool_call_ids:
                    end_event = ToolCallEndEvent(
                        type=EventType.TOOL_CALL_END,
                        tool_call_id=tool_call.tool_call_id,  # type: ignore
                    )
                    async for event in emit_event(end_event):
                        yield event

        # Handle reasoning
        elif chunk.event == RunEvent.reasoning_started:
            step_event = StepStartedEvent(type=EventType.STEP_STARTED, step_name="reasoning")
            async for event in emit_event(step_event):
                yield event
        elif chunk.event == RunEvent.reasoning_completed:
            step_event = StepFinishedEvent(type=EventType.STEP_FINISHED, step_name="reasoning")
            async for event in emit_event(step_event):
                yield event

        # Handle the lifecycle end event
        elif chunk.event == RunEvent.run_completed:
            # End remaining active tool calls if needed
            for tool_call_id in list(event_buffer.active_tool_call_ids):
                if tool_call_id not in event_buffer.ended_tool_call_ids:
                    end_event = ToolCallEndEvent(
                        type=EventType.TOOL_CALL_END,
                        tool_call_id=tool_call_id,
                    )
                    async for event in emit_event(end_event):
                        yield event

            # End the message and run, denoting the end of the session
            if message_started:
                end_message_event = TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id)
                async for event in emit_event(end_message_event):
                    yield event
            run_finished_event = RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id)
            async for event in emit_event(run_finished_event):
                yield event
