import copy
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

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

from agno.os.interfaces.agui.helpers import (
    extract_response_chunk_content,
    extract_team_response_chunk_content,
    format_reasoning_step_delta,
)
from agno.os.interfaces.agui.state import EventBuffer
from agno.run.agent import ReasoningCompletedEvent as AgentReasoningCompletedEvent
from agno.run.agent import ReasoningContentDeltaEvent as AgentReasoningContentDeltaEvent
from agno.run.agent import ReasoningStartedEvent as AgentReasoningStartedEvent
from agno.run.agent import ReasoningStepEvent as AgentReasoningStepEvent
from agno.run.agent import RunEvent, RunOutputEvent, RunPausedEvent
from agno.run.team import ReasoningCompletedEvent as TeamReasoningCompletedEvent
from agno.run.team import ReasoningContentDeltaEvent as TeamReasoningContentDeltaEvent
from agno.run.team import ReasoningStartedEvent as TeamReasoningStartedEvent
from agno.run.team import ReasoningStepEvent as TeamReasoningStepEvent
from agno.run.team import TeamRunEvent, TeamRunOutputEvent


def create_state_delta_events(
    run_state: Optional[Dict[str, Any]],
    event_buffer: EventBuffer,
) -> List[BaseEvent]:
    """Compute state delta and return StateDeltaEvent if state changed."""
    if run_state is None:
        return []
    ops = event_buffer.compute_state_delta(run_state)
    if ops is None:
        return []
    event_buffer.set_state_snapshot(run_state)
    return [StateDeltaEvent(type=EventType.STATE_DELTA, delta=ops)]


def create_events_from_chunk(
    chunk: Union[RunOutputEvent, TeamRunOutputEvent],
    message_id: str,
    message_started: bool,
    event_buffer: EventBuffer,
    run_state: Optional[Dict[str, Any]] = None,
) -> Tuple[List[BaseEvent], bool, str]:
    """Process a single chunk and return events to emit + updated message_started state."""
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
        if not message_started:
            message_started = True
            message_id = event_buffer.start_text_message()
            event_buffer.clear_pending_tool_calls_parent_id()
            start_event = TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=message_id,
                role="assistant",
            )
            events_to_emit.append(start_event)

        if content != "":
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

            current_message_id = message_id
            if message_started:
                end_message_event = TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=current_message_id)
                events_to_emit.append(end_message_event)
                event_buffer.set_pending_tool_calls_parent_id(current_message_id)
                message_started = False
                message_id = str(uuid.uuid4())

            parent_message_id = event_buffer.get_parent_message_id_for_tool_call()

            if not parent_message_id:
                parent_message_id = str(uuid.uuid4())
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

                events_to_emit.extend(create_state_delta_events(run_state, event_buffer))

    # Handle reasoning events
    elif isinstance(chunk, (AgentReasoningStartedEvent, TeamReasoningStartedEvent)):
        if message_started:
            events_to_emit.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id))
            message_started = False
            message_id = str(uuid.uuid4())
        reasoning_id = event_buffer.start_reasoning()
        events_to_emit.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
        events_to_emit.append(
            ReasoningMessageStartEvent(
                type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"
            )
        )

    elif isinstance(chunk, (AgentReasoningContentDeltaEvent, TeamReasoningContentDeltaEvent)):
        if message_started:
            events_to_emit.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id))
            message_started = False
            message_id = str(uuid.uuid4())
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
        if message_started:
            events_to_emit.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id))
            message_started = False
            message_id = str(uuid.uuid4())
        reasoning_id, is_new = event_buffer.ensure_reasoning_started()
        if is_new:
            events_to_emit.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
            events_to_emit.append(
                ReasoningMessageStartEvent(
                    type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"
                )
            )
        step_num = event_buffer.next_reasoning_step()
        delta = format_reasoning_step_delta(chunk.content, step_num)
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
        try:
            custom_event_name = chunk.__class__.__name__
        except Exception:
            custom_event_name = chunk.event

        try:
            custom_event_value = chunk.to_dict()
        except Exception:
            custom_event_value = chunk.content  # type: ignore

        custom_event = CustomEvent(name=custom_event_name, value=custom_event_value)
        events_to_emit.append(custom_event)

    # Catch-all: emit unmapped events as RawEvent
    elif not is_content_event:
        try:
            raw_dict = chunk.to_dict()
        except Exception:
            raw_dict = {"event": str(chunk.event)}
        events_to_emit.append(RawEvent(type=EventType.RAW, event=raw_dict, source="agno"))

    return events_to_emit, message_started, message_id


def create_completion_events(
    chunk: Union[RunOutputEvent, TeamRunOutputEvent],
    event_buffer: EventBuffer,
    message_started: bool,
    message_id: str,
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
) -> List[BaseEvent]:
    """Create events for run completion (orphan closure, final snapshot, RUN_FINISHED)."""
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
            end_event = ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id)
            events_to_emit.append(end_event)

    # End the message if started
    if message_started:
        end_message_event = TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id)
        events_to_emit.append(end_message_event)

    # Emit external execution tools for paused runs
    if isinstance(chunk, RunPausedEvent):
        external_tools = chunk.tools_awaiting_external_execution
        if external_tools:
            assistant_message_id = str(uuid.uuid4())
            assistant_start_event = TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=assistant_message_id,
                role="assistant",
            )
            events_to_emit.append(assistant_start_event)

            if chunk.content:
                content_event = TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=assistant_message_id,
                    delta=str(chunk.content),
                )
                events_to_emit.append(content_event)

            assistant_end_event = TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=assistant_message_id,
            )
            events_to_emit.append(assistant_end_event)

            for tool in external_tools:
                if tool.tool_call_id is None or tool.tool_name is None:
                    continue

                start_event = ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool.tool_call_id,
                    tool_call_name=tool.tool_name,
                    parent_message_id=assistant_message_id,
                )
                events_to_emit.append(start_event)

                args_event = ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool.tool_call_id,
                    delta=json.dumps(tool.tool_args),
                )
                events_to_emit.append(args_event)

                end_event = ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool.tool_call_id)
                events_to_emit.append(end_event)

    # Emit final state snapshot
    if run_state is not None:
        authoritative_state = getattr(chunk, "session_state", None)
        final_state = authoritative_state if authoritative_state is not None else run_state
        snapshot_event = StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(final_state))
        events_to_emit.append(snapshot_event)

    run_finished_event = RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id)
    events_to_emit.append(run_finished_event)

    return events_to_emit


def emit_event_logic(event: BaseEvent, event_buffer: EventBuffer) -> List[BaseEvent]:
    """Process an event and update buffer state for tracking."""
    events_to_emit: List[BaseEvent] = [event]

    if event.type == EventType.TOOL_CALL_START:
        tool_call_id = getattr(event, "tool_call_id", None)
        if tool_call_id:
            event_buffer.start_tool_call(tool_call_id)
    elif event.type == EventType.TOOL_CALL_END:
        tool_call_id = getattr(event, "tool_call_id", None)
        if tool_call_id:
            event_buffer.end_tool_call(tool_call_id)

    return events_to_emit
