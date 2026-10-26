import copy
import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional

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
from ag_ui.core import (
    RunErrorEvent as AGUIRunErrorEvent,
)
from pydantic import BaseModel

from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.os.interfaces.agui.state import SpanTransition, StreamState
from agno.os.interfaces.agui.utils import to_json_str
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunEvent
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.base import BaseRunOutputEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import TeamRunEvent
from agno.run.workflow import WorkflowRunEvent
from agno.utils.log import log_warning
from agno.utils.message import get_text_from_message

EventHandler = Callable[[BaseRunOutputEvent, StreamState], List[BaseEvent]]


def _message_text(content: Any) -> str:
    """Read message shaped content as text, and nothing at all out of a shape it cannot read.

    ``get_text_from_message`` is written for message content and probes a list's first
    element for keys, which raises on a list of scalars. Content reaching the mapper is
    typed as anything, so a shape the reading cannot take is not a failure here. Reading
    one delta must never cost the client the rest of the run: an exception leaving the
    mapper is caught by the route, which ends the run with an error in place of
    everything it had left to send, and closes none of the spans the client holds open.
    What was dropped is logged, because content vanishing without a trace is the fault
    this guard was written to remove.
    """
    try:
        return get_text_from_message(content)
    except (TypeError, ValueError, AttributeError) as e:
        log_warning(f"AG-UI could not read content of type {type(content).__name__} as text: {e}")
        return ""


def _extract_response_chunk_content(response: RunContentEvent) -> str:
    # RunContentEvent can carry text in .messages (list) or .content (direct)
    # AG-UI needs a plain string for TEXT_MESSAGE_CONTENT delta
    if hasattr(response, "messages") and response.messages:  # type: ignore
        for msg in reversed(response.messages):  # type: ignore
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                return _message_text(msg.content)
    return _message_text(response.content) if response.content is not None else ""


def _extract_team_response_chunk_content(response: TeamRunContentEvent) -> str:
    # Team responses nest member outputs — fold them into one text delta
    members_content = []
    if hasattr(response, "member_responses") and response.member_responses:  # type: ignore
        for member_resp in response.member_responses:  # type: ignore
            if isinstance(member_resp, RunContentEvent):
                member_content = _extract_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
            elif isinstance(member_resp, TeamRunContentEvent):
                member_content = _extract_team_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
    members_response = "\n".join(members_content) if members_content else ""
    main_content = _message_text(response.content) if response.content is not None else ""
    return main_content + members_response


def _json_text(value: Any) -> str:
    """Render a value as the readable JSON a reader sees in the transcript, and never raise.

    A step returns whatever its executor returned, so a record it returns holds values the
    standard serializer has no reading for: a datetime, a set, a model. Each of those is
    rendered as its own text, which keeps the rest of the record readable and keeps the
    run alive: an exception here is caught by the route and turned into the run's error,
    so one unreadable value would abort a run that was otherwise fine.
    """
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


# Roles whose turns in a transcript are not the step's own answer: what was written to
# the step, and what its tools wrote back into it. A tool payload read as the step's
# answer is wrong text on the wire, not missing text.
_NON_ANSWER_ROLES = frozenset({"user", "system", "developer", "tool"})


def _message_role(item: Any) -> Optional[str]:
    """The role an element of a message list declares, or None when it declares none."""
    if isinstance(item, Message):
        return item.role
    if isinstance(item, dict) and isinstance(item.get("role"), str):
        return item["role"]
    return None


def _message_body(item: Any) -> Any:
    """The content an element of a message list carries."""
    if isinstance(item, Message):
        return item.content
    if isinstance(item, dict):
        return item.get("content")
    return item


def _step_content_to_text(content: Any) -> str:
    """Render a completed step's own output as the text a reader sees in the transcript.

    A step returns whatever its executor returned, so its content is message shaped only
    some of the time. Message shaped content keeps the reading the rest of the interface
    gives it, and every other shape is rendered as something readable rather than dropped
    or raised on. Content that carries nothing to read renders as the empty string, which
    opens no message at all.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        roles = [_message_role(item) for item in content]
        if any(role is not None for role in roles):
            # A list of messages is a transcript, not message content. Read as message
            # content it yields the user turns, which would send the caller's own prompt
            # back as the step's answer and drop the answer, so the turns that are not
            # the step's answer are dropped here instead and what it replied is kept.
            return "\n".join(
                text
                for text in (
                    _step_content_to_text(_message_body(item))
                    for item, role in zip(content, roles)
                    if role not in _NON_ANSWER_ROLES
                )
                if text
            )
        # A list of records may be message content, which has an established text
        # reading. Anything else is a plain sequence, rendered one element per line.
        if content and all(isinstance(item, dict) for item in content):
            from_message_shape = _message_text(content)
            if from_message_shape:
                return from_message_shape
        return "\n".join(text for text in (_step_content_to_text(item) for item in content) if text)
    if isinstance(content, dict):
        if not content:
            return ""
        # A record whose only key is named for content is that content and nothing else.
        # Every other record is rendered whole, because a key named content earns no
        # right to speak for the keys beside it.
        if set(content) == {"content"}:
            return _step_content_to_text(content["content"])
        return _json_text(content)
    if isinstance(content, Message):
        return _step_content_to_text(content.content)
    if isinstance(content, BaseModel):
        # A model holding a value pydantic has no serializer for raises here, and the
        # model's own text still says what the step produced.
        try:
            return content.model_dump_json(indent=2, exclude_none=True)
        except (TypeError, ValueError):
            return str(content)
    return str(content)


def _tool_args_json(tool_args: Optional[Dict[str, Any]]) -> str:
    """Serialize a tool call's arguments for whatever renders it, and never raise.

    The render reads the arguments as an object, so every reading here is one: a call
    made without arguments is an empty object rather than a null, and an argument the
    standard serializer has no reading for is rendered as its text under its own name
    rather than the whole record being replaced by a string of itself. A record that
    defeats even that, because a key or a value cannot be rendered at all, comes back as
    the empty object, which the render can read and finds nothing in.

    A call announced as it starts and one held for approval are the same thing to the
    client, which is why both are written this way. Raising instead costs the client the
    run: an exception here is caught by the route, which ends the run with an error in
    place of everything it still had to send, and a paused run's cards are built in the
    same batch as its terminal event, so none of them would go out at all. No model
    writes a record the first reading below cannot take, so the rest is there to keep
    that promise rather than to serve a call anyone has made.
    """
    if not tool_args:
        return "{}"
    try:
        return json.dumps(tool_args, default=str)
    except (TypeError, ValueError):
        pass
    # Reached by a key the standard serializer refuses and by a record that refers to
    # itself. Rendering each argument on its own settles both, since a key is named and
    # a value's repr closes a cycle the serializer would walk forever.
    try:
        return json.dumps({str(key): repr(value) for key, value in tool_args.items()})
    except Exception:
        return "{}"


def _format_reasoning_step(step: Optional[ReasoningStep], step_number: int = 0) -> str:
    """Format a ReasoningStep as text for REASONING_MESSAGE_CONTENT."""
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


def _span_events(transitions: List[SpanTransition]) -> List[BaseEvent]:
    """Render the span transitions a state change produced as AG-UI events."""
    events: List[BaseEvent] = []
    for transition in transitions:
        if transition.started:
            events.append(StepStartedEvent(type=EventType.STEP_STARTED, step_name=transition.step_name))
        else:
            events.append(StepFinishedEvent(type=EventType.STEP_FINISHED, step_name=transition.step_name))
    return events


def _emit_state_delta(state: StreamState) -> List[BaseEvent]:
    if state.run_state is None:
        return []
    ops = state.compute_state_delta(state.run_state)
    if ops is None:
        return []
    state.set_state_snapshot(state.run_state)
    return [StateDeltaEvent(type=EventType.STATE_DELTA, delta=ops)]


def close_open_spans(state: StreamState) -> List[BaseEvent]:
    """End any reasoning, tool call, text message or step still open, so a terminal event never leaves a dangling span.

    The batch a caller assembles around these closings can be lost whole: a terminal
    handler puts the closings and the run's ending in one list, and anything that raises
    while the rest of that list is built discards the closings with it. So the closings
    are remembered on the state, and a second call hands back the same ones rather than
    the nothing a drained state would yield. The caller that ends the run after such a
    failure therefore still closes what the client is holding open.

    Remembering them makes this a once-per-stream closing, which is sound only because
    the terminal call is the last thing a stream builds, so no two callers can both send
    what it returns. A caller added mid-stream would replay a stale list instead.

    Callers get their own list, because a terminal handler appends its ending to what it
    is given and that must not become part of what a later call replays.
    """
    if state.built_closings is not None:
        return list(state.built_closings)

    events: List[BaseEvent] = []

    # Close orphaned reasoning session
    if state.reasoning_message_id is not None:
        events.append(
            ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=state.reasoning_message_id)
        )
        events.append(ReasoningEndEvent(type=EventType.REASONING_END, message_id=state.reasoning_message_id))
        state.end_reasoning()

    # Close remaining active tool calls
    for tool_call_id in list(state.active_tool_call_ids):
        if tool_call_id not in state.ended_tool_call_ids:
            events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id))
            state.end_tool_call(tool_call_id)

    # Close open text message
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

    # Close workflow steps still open, innermost first
    events.extend(_span_events(state.close_all_spans()))

    state.built_closings = events
    return list(events)


def on_run_content(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    event = getattr(chunk, "event", None)
    if event == RunEvent.run_content:
        content = _extract_response_chunk_content(chunk)  # type: ignore
    elif event == TeamRunEvent.run_content:
        content = _extract_team_response_chunk_content(chunk)  # type: ignore
    else:
        content = ""

    if not state.text_message_open:
        message_id = state.open_text_message()
        state.clear_pending_tool_calls_parent_id()
        events.append(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=message_id,
                role="assistant",
            )
        )

    if content:
        # A workflow step stamps its id onto the events its executor produces
        state.record_text_delta(step_id=getattr(chunk, "step_id", None))
        events.append(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=state.text_message_id,
                delta=content,
            )
        )

    return events


def on_tool_call_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return events

    if tool.tool_call_id is None or tool.tool_name is None:
        log_warning(f"AG-UI dropped a tool call with no id or name: {tool.tool_name!r} {tool.tool_call_id!r}")
        return events

    # Close open text message before tool call
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.set_pending_tool_calls_parent_id(state.text_message_id)
        state.close_text_message()

    parent_message_id = state.get_parent_message_id_for_tool_call()

    # Clients that render a tool call nested under an assistant turn need one to nest it
    # under. AG-UI itself allows parent_message_id to be absent, so this is what those
    # clients need rather than what the protocol demands.
    if not parent_message_id:
        parent_message_id = str(uuid.uuid4())
        events.append(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=parent_message_id,
                role="assistant",
            )
        )
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=parent_message_id))
        state.set_pending_tool_calls_parent_id(parent_message_id)

    events.append(
        ToolCallStartEvent(
            type=EventType.TOOL_CALL_START,
            tool_call_id=tool.tool_call_id,
            tool_call_name=tool.tool_name,
            parent_message_id=parent_message_id,
        )
    )

    events.append(
        ToolCallArgsEvent(
            type=EventType.TOOL_CALL_ARGS,
            tool_call_id=tool.tool_call_id,
            delta=_tool_args_json(tool.tool_args),
        )
    )

    state.start_tool_call(tool.tool_call_id)
    return events


def on_tool_call_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return events

    if tool.tool_call_id is None:
        log_warning(f"AG-UI dropped the completion of tool {tool.tool_name!r}, which carries no tool call id")
        return events

    if tool.tool_call_id in state.ended_tool_call_ids:
        # The client was told once that this call ended, and the state the event carries
        # is owed all the same: the run moved on between the two reports of the call.
        return _emit_state_delta(state)

    events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool.tool_call_id))
    state.end_tool_call(tool.tool_call_id)

    if tool.result is not None:
        content = to_json_str(tool.result)
        events.append(
            ToolCallResultEvent(
                type=EventType.TOOL_CALL_RESULT,
                tool_call_id=tool.tool_call_id,
                content=content,
                role="tool",
                # Use tool_call_id as message_id so frontend can link result to the tool call
                message_id=tool.tool_call_id,
            )
        )

    events.extend(_emit_state_delta(state))
    return events


def on_reasoning_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    # Close open text message before reasoning
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

    reasoning_id = state.start_reasoning()
    events.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
    events.append(
        ReasoningMessageStartEvent(type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning")
    )
    return events


def on_reasoning_content_delta(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    # Close open text message before reasoning
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

    reasoning_id, is_new = state.ensure_reasoning_started()
    if is_new:
        events.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
        events.append(
            ReasoningMessageStartEvent(
                type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"
            )
        )

    content = getattr(chunk, "reasoning_content", None)
    if content:
        events.append(
            ReasoningMessageContentEvent(
                type=EventType.REASONING_MESSAGE_CONTENT, message_id=reasoning_id, delta=content
            )
        )
    return events


def on_reasoning_step(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    # Close open text message before reasoning
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

    reasoning_id, is_new = state.ensure_reasoning_started()
    if is_new:
        events.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
        events.append(
            ReasoningMessageStartEvent(
                type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"
            )
        )

    step_num = state.next_reasoning_step()
    step_content = getattr(chunk, "content", None)
    delta = _format_reasoning_step(step_content, step_num)
    if delta:
        events.append(
            ReasoningMessageContentEvent(type=EventType.REASONING_MESSAGE_CONTENT, message_id=reasoning_id, delta=delta)
        )
    return events


def on_reasoning_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    if state.reasoning_message_id is not None:
        reasoning_id = state.reasoning_message_id
        events.append(ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=reasoning_id))
        events.append(ReasoningEndEvent(type=EventType.REASONING_END, message_id=reasoning_id))
        state.end_reasoning()

    return events


def on_workflow_step_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    return _span_events(
        state.open_step(
            step_name=getattr(chunk, "step_name", None),
            step_id=getattr(chunk, "step_id", None),
            parent_step_id=getattr(chunk, "parent_step_id", None),
            step_index=getattr(chunk, "step_index", None),
        )
    )


def on_workflow_step_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    step_name = getattr(chunk, "step_name", None)
    step_id = getattr(chunk, "step_id", None)
    step = state.close_step(
        step_name=step_name,
        step_id=step_id,
        step_index=getattr(chunk, "step_index", None),
    )

    events: List[BaseEvent] = []

    # Each step gets its own assistant message rather than one message spanning the run
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

    if step is None:
        log_warning(f"AG-UI matched the completion of workflow step '{step_name}' to no step it had started")

    # A step run by a plain function streams nothing, so its output exists only here, and
    # a step whose output the client already has must not send it a second time. The text
    # is read before the claim because a completion carrying nothing has no output to
    # claim: claiming it would tell every step containing this one that its own output had
    # already been sent, and their output would never be emitted.
    text = _step_content_to_text(getattr(chunk, "content", None))
    if text and state.claim_step_output(step, step_id):
        message_id = state.open_text_message()
        state.clear_pending_tool_calls_parent_id()
        events.append(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=message_id,
                role="assistant",
            )
        )
        events.append(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=text,
            )
        )
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id))
        state.close_text_message()

    # Finish this step, and every step it contained, innermost first
    events.extend(_span_events(state.flush_spans()))
    return events


def on_custom_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    try:
        custom_event_name = chunk.__class__.__name__
    except Exception:
        custom_event_name = str(getattr(chunk, "event", "CustomEvent"))

    try:
        custom_event_value: Any = chunk.to_dict()
    except Exception:
        custom_event_value = getattr(chunk, "content", None)

    return [CustomEvent(name=custom_event_name, value=custom_event_value)]


def on_unknown_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    try:
        raw_dict: Dict[str, Any] = chunk.to_dict()
    except Exception:
        raw_dict = {"event": str(getattr(chunk, "event", "unknown"))}
    return [RawEvent(type=EventType.RAW, event=raw_dict, source="agno")]


def _iter_step_results(results: Optional[List[Any]]) -> Iterator[Any]:
    """Walk workflow step results depth first, innermost first.

    An element is either a step result or a list of them, because a container step groups
    the results of its children. A step result can also report children of its own under
    ``StepOutput.steps``. Only the innermost result carries the real error, so both forms
    have to be descended into.
    """
    for result in results or []:
        if result is None:
            continue
        if isinstance(result, list):
            yield from _iter_step_results(result)
            continue
        yield from _iter_step_results(getattr(result, "steps", None))
        yield result


def _last_step_result(results: Optional[List[Any]]) -> Optional[Any]:
    """Return the step result the run ended on, or None when it produced none.

    The run's own steps are sequential, so the last of them is where the run stopped. A
    grouped element stands in for one of those steps and is not itself a result, so a
    trailing group is descended into for its own last result. A grouped step that reports
    its children under ``StepOutput.steps`` is not descended into: the children of a
    parallel step are ordered by declaration rather than by when they ran, so the last of
    them is not the last thing that happened. The step's own result speaks for them.
    """
    for result in reversed(results or []):
        if result is None:
            continue
        if isinstance(result, list):
            last = _last_step_result(result)
            if last is None:
                continue
            return last
        return result
    return None


def _reports_failure(result: Any) -> bool:
    """Whether a step result, or anything it groups, failed.

    Every container step in the engine folds its children's failures into its own success
    flag, so a container reporting success over a failed child is a summary that lost the
    failure rather than one that tolerated it.
    """
    if not getattr(result, "success", True):
        return True
    return any(_reports_failure(child) for child in _iter_step_results(getattr(result, "steps", None)))


def _failed_step_error(chunk: BaseRunOutputEvent) -> Optional[str]:
    """Return the failure that ended the run, if this completion event reports one.

    A failed step result is fatal only when the run stopped there. The engine aborts a
    fatal step failure by raising, so nothing can follow it. A step that opts out of
    aborting, through skip_on_failure or an on_error policy of skip, leaves a failed
    result behind and the engine carries on, so further results follow it and the run
    really did complete. The last result the run produced therefore decides, and the
    reason it reports is read from that result rather than from a failure the run
    survived earlier.

    The known limit of that rule: a step that opted out of aborting and happened to run
    last leaves nothing behind it, so it is read as the run's ending. The engine records
    the tolerance only in the result's prose content, and each policy words it
    differently, so there is nothing here to read it from.
    """
    deciding = _last_step_result(getattr(chunk, "step_results", None))
    if deciding is None or not _reports_failure(deciding):
        return None

    failed = [result for result in _iter_step_results([deciding]) if not getattr(result, "success", True)]
    for result in failed:
        error = getattr(result, "error", None)
        if error:
            return str(error)

    # A container step can be marked failed while only its children name the reason
    step_name = getattr(failed[0], "step_name", None)
    return f"Workflow step '{step_name}' failed" if step_name else "Workflow step failed"


def on_run_error(
    chunk: BaseRunOutputEvent,
    state: StreamState,
    message: Optional[str] = None,
    code: Optional[str] = None,
) -> List[BaseEvent]:
    """Close open spans, then emit the terminal AG-UI error event. Nothing may follow RUN_ERROR."""
    try:
        raw_event: Any = chunk.to_dict()
    except Exception:
        raw_event = {"event": str(getattr(chunk, "event", "RunError"))}

    # Workflow error events carry the reason on `error`, agent and team ones on `content`
    if message is None:
        message = getattr(chunk, "content", None) or getattr(chunk, "error", None) or "Run failed"
    if code is None:
        code = getattr(chunk, "error_type", None)

    events = close_open_spans(state)
    events.append(
        AGUIRunErrorEvent(
            type=EventType.RUN_ERROR,
            message=str(message),
            code=code,
            rawEvent=raw_event,
        )
    )
    return events


def on_run_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events = close_open_spans(state)

    # 1. Collect paused tools for frontend rendering
    paused_tools: List[ToolExecution] = []
    if isinstance(chunk, AgentRunPausedEvent):
        paused_tools = (
            chunk.tools_awaiting_external_execution
            + chunk.tools_requiring_confirmation
            + chunk.tools_requiring_user_input
        )
    elif isinstance(chunk, TeamRunPausedEvent):
        # Leader tools from .tools, member tools from active_requirements
        paused_tools = (
            chunk.tools_awaiting_external_execution
            + chunk.tools_requiring_confirmation
            + chunk.tools_requiring_user_input
        )
        for req in chunk.active_requirements:
            if req.member_agent_id and req.tool_execution:
                paused_tools.append(req.tool_execution)

    if paused_tools:
        assistant_message_id = str(uuid.uuid4())
        events.append(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=assistant_message_id,
                role="assistant",
            )
        )

        content = getattr(chunk, "content", None)
        if content:
            events.append(
                TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=assistant_message_id,
                    delta=str(content),
                )
            )

        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=assistant_message_id))

        for tool in paused_tools:
            if tool.tool_call_id is None or tool.tool_name is None:
                continue

            events.append(
                ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool.tool_call_id,
                    tool_call_name=tool.tool_name,
                    parent_message_id=assistant_message_id,
                )
            )

            events.append(
                ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool.tool_call_id,
                    delta=_tool_args_json(tool.tool_args),
                )
            )

            events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool.tool_call_id))

    # Emit final state snapshot
    if state.run_state is not None:
        authoritative_state = getattr(chunk, "session_state", None)
        final_state = authoritative_state if authoritative_state is not None else state.run_state
        events.append(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(final_state)))

    events.append(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=state.thread_id, run_id=state.run_id))
    return events


def _normalize_event(event: str) -> str:
    """Strip 'Team' prefix so agent and team events use the same handlers."""
    return event.removeprefix("Team")


# Maps normalized event names to handler functions
HANDLERS: Dict[str, EventHandler] = {
    RunEvent.run_content.value: on_run_content,
    RunEvent.tool_call_started.value: on_tool_call_started,
    RunEvent.tool_call_completed.value: on_tool_call_completed,
    RunEvent.reasoning_started.value: on_reasoning_started,
    RunEvent.reasoning_content_delta.value: on_reasoning_content_delta,
    RunEvent.reasoning_step.value: on_reasoning_step,
    RunEvent.reasoning_completed.value: on_reasoning_completed,
    RunEvent.custom_event.value: on_custom_event,
    WorkflowRunEvent.step_started.value: on_workflow_step_started,
    WorkflowRunEvent.step_completed.value: on_workflow_step_completed,
}

# Terminal engine events, normalized so a team event reuses its agent name. A run's
# stream ends on one of these, and membership decides the run's disposition except for a
# completion event, whose step results are read by `_failed_step_error`. A run whose
# stream never reaches the mapper ends in the route's own error event instead.

# Ends the run as a success
_FINISHED_EVENTS = frozenset(
    {
        RunEvent.run_completed.value,
        RunEvent.run_paused.value,
        WorkflowRunEvent.workflow_completed.value,
    }
)

# A paused workflow surfaces no tool calls and offers the client no way to resume, so
# reporting it as a finish would be a false success. It terminates like a cancellation.
_PAUSE_EVENTS = frozenset(
    {
        WorkflowRunEvent.workflow_paused.value,
        WorkflowRunEvent.step_paused.value,
        WorkflowRunEvent.step_executor_paused.value,
        WorkflowRunEvent.condition_paused.value,
        WorkflowRunEvent.router_paused.value,
        # An output review and a loop iteration review both pause under this name, and
        # the engine returns straight after it, so nothing else reports that ending.
        WorkflowRunEvent.step_output_review.value,
    }
)

# The workflow's own report that it did not finish. The engine repeats itself here: a
# cancellation is followed by a completion event carrying the cancellation text, and a
# pause arrives once as a step event and again as a workflow event. So once one of these
# has been seen, no later success can overrule it.
_WORKFLOW_UNFINISHED_EVENTS = (
    frozenset(
        {
            WorkflowRunEvent.workflow_error.value,
            WorkflowRunEvent.workflow_cancelled.value,
            WorkflowRunEvent.step_error.value,
        }
    )
    | _PAUSE_EVENTS
)

# Ends the run without a success. An agent or team error is included but never latches:
# inside a workflow it belongs to a step's executor, and a step is free to carry on past it.
_UNFINISHED_EVENTS = _WORKFLOW_UNFINISHED_EVENTS | frozenset({RunEvent.run_error.value})


@dataclass
class _RunOutcome:
    """How one terminal engine event says the run ended."""

    chunk: BaseRunOutputEvent
    finished: bool
    message: Optional[str] = None
    code: Optional[str] = None
    final: bool = False


def _event_value(chunk: BaseRunOutputEvent) -> Optional[str]:
    event = getattr(chunk, "event", None)
    if event is None:
        return None
    return event.value if hasattr(event, "value") else str(event)


def _ended_an_inner_run(chunk: BaseRunOutputEvent) -> bool:
    """Whether a terminal event ended a run other than the one the client is watching.

    A nested workflow reports its ending on its parent's stream under a nesting depth
    above zero. A team member and a sub-agent report theirs with the run that started
    them on ``parent_run_id`` and the depth left at zero, so depth alone lets a member's
    ending decide the run the client asked for.

    Those two markers are not every inner run. A workflow step's own agent or team
    executor reports its ending with neither, and is deliberately let through: the
    workflow's own terminal event arrives afterwards and overrules it, and
    ``_UNFINISHED_EVENTS`` is written so an executor's error never latches.
    """
    return bool(getattr(chunk, "nested_depth", 0)) or getattr(chunk, "parent_run_id", None) is not None


def _pause_message(chunk: BaseRunOutputEvent) -> str:
    step_name = getattr(chunk, "paused_step_name", None) or getattr(chunk, "step_name", None)
    return f"Workflow paused at step '{step_name}'" if step_name else "Workflow paused"


def _classify_terminal(chunk: BaseRunOutputEvent, normalized: str) -> _RunOutcome:
    final = normalized in _WORKFLOW_UNFINISHED_EVENTS

    if normalized in _PAUSE_EVENTS:
        return _RunOutcome(chunk, finished=False, message=_pause_message(chunk), code=normalized, final=final)

    if normalized == WorkflowRunEvent.workflow_cancelled.value:
        # A cancelled run is not a failure, but it is not a success either. It carries its
        # reason on `reason`, and gets a code clients can tell apart from a real failure.
        reason = getattr(chunk, "reason", None) or getattr(chunk, "content", None) or "Run cancelled"
        return _RunOutcome(chunk, finished=False, message=str(reason), code=normalized, final=final)

    if normalized in _UNFINISHED_EVENTS:
        return _RunOutcome(chunk, finished=False, final=final)

    # A step that failed without aborting the run rides along on a completion event, so
    # the payload decides whether this completion is really a success.
    step_error = _failed_step_error(chunk)
    if step_error is not None:
        return _RunOutcome(chunk, finished=False, message=step_error)

    return _RunOutcome(chunk, finished=True)


class RunTerminalTracker:
    """Decides the single terminal AG-UI event a run's stream ends on.

    The engine reports a run's ending more than once and from more than one level: a
    cancelled run is followed by a completion event repeating the cancellation text, a
    pause arrives as a step event and again as a workflow event, and a nested workflow
    reports its own ending onto the same stream. Every one of those is read here, so a
    new engine outcome is handled by naming it in the sets above rather than by adding
    another rule somewhere along the stream.
    """

    def __init__(self) -> None:
        self._outcome: Optional[_RunOutcome] = None
        self._reported_unfinished = False

    def observe(self, chunk: BaseRunOutputEvent) -> bool:
        """Take a chunk that reports how a run ended. Returns True when it was taken."""
        event_value = _event_value(chunk)
        if event_value is None:
            return False

        normalized = _normalize_event(event_value)
        if normalized not in _FINISHED_EVENTS and normalized not in _UNFINISHED_EVENTS:
            return False

        # An ending belonging to a run the client never asked for is taken off the stream
        # without being allowed to decide the run the client is watching.
        if _ended_an_inner_run(chunk):
            return True

        candidate = _classify_terminal(chunk, normalized)

        # Once the workflow has reported that the run did not finish, that report stands
        # for the rest of the stream. Only another report from the workflow itself may
        # replace it: a later success is the engine repeating the ending it already gave,
        # and an agent or team error belongs to a step's executor rather than to the run.
        if self._reported_unfinished and not candidate.final:
            return True

        self._reported_unfinished = self._reported_unfinished or candidate.final
        self._outcome = candidate
        return True

    def emit(self, state: StreamState) -> List[BaseEvent]:
        """Emit the terminal events, synthesizing a success if the stream just ran out."""
        outcome = self._outcome or _RunOutcome(RunCompletedEvent(), finished=True)
        if outcome.finished:
            return on_run_completed(outcome.chunk, state)
        return on_run_error(outcome.chunk, state, message=outcome.message, code=outcome.code)


def process_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    """Process a single Agno event and return AG-UI events to emit."""
    event_value = _event_value(chunk)
    if event_value is None:
        return on_unknown_event(chunk, state)

    normalized = _normalize_event(event_value)

    handler = HANDLERS.get(normalized)
    if handler:
        return handler(chunk, state)

    return on_unknown_event(chunk, state)
