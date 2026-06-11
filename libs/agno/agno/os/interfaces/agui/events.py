"""Per-chunk Agno → AG-UI event translation."""

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
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from agno.os.interfaces.agui.messages import (
    extract_response_chunk_content,
    extract_team_response_chunk_content,
)
from agno.os.interfaces.agui.state import EventBuffer, create_state_delta_events
from agno.reasoning.step import ReasoningStep
from agno.run.agent import ReasoningCompletedEvent as AgentReasoningCompletedEvent
from agno.run.agent import ReasoningContentDeltaEvent as AgentReasoningContentDeltaEvent
from agno.run.agent import ReasoningStartedEvent as AgentReasoningStartedEvent
from agno.run.agent import ReasoningStepEvent as AgentReasoningStepEvent
from agno.run.agent import RunEvent, RunOutputEvent
from agno.run.team import ReasoningCompletedEvent as TeamReasoningCompletedEvent
from agno.run.team import ReasoningContentDeltaEvent as TeamReasoningContentDeltaEvent
from agno.run.team import ReasoningStartedEvent as TeamReasoningStartedEvent
from agno.run.team import ReasoningStepEvent as TeamReasoningStepEvent
from agno.run.team import TeamRunEvent, TeamRunOutputEvent


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


def create_events_from_chunk(
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

            # Get the parent message ID - uses pending parent if set, so sequential tool calls share a parent
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


def emit_event_logic(event: BaseEvent, event_buffer: EventBuffer) -> List[BaseEvent]:
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
