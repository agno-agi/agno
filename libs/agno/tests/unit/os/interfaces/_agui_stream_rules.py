"""Framing rules the AG-UI reference client enforces on an event stream.

The TypeScript client verifies every stream it receives and aborts the run on the first
violation, so a sequence this suite accepts but the client rejects is a defect the
browser sees and the tests do not. Per-scenario assertions cannot catch that: they check
the two deltas or the three span names the author had in mind, never the properties that
hold over the whole stream.

Five families of the client's rules are checked here, and nothing else: run framing,
step spans, text-message framing, tool-call framing, and the shape a tool call's
arguments arrive in. That is a subset, not a port. The client also rejects a text
message opened while a tool call is in flight and the reverse, and it type-checks the
rest of each payload; neither is checked here, so a stream this helper accepts is not
certified against the client, only shown to be free of the faults below.

One rule here is a house rule rather than the client's: an empty text message. The
client accepts a message that carries no content, and the shipped mapper emits one
deliberately, both as the parent message a tool call needs and as the assistant turn a
pause with no text still has to open. What that leaves worth catching is the accidental
shape, a message opened and then closed only after other events have gone out with no
content ever arriving, so that is what the rule says.

The mappers emit the body of a stream; the HTTP route prepends RUN_STARTED and the
initial state snapshot. The RUN_STARTED rule therefore applies only when the event is
present, which keeps the checker honest for a served stream without weakening it here.
"""

import json
from typing import Any, Dict, List, Optional

from ag_ui.core import EventType

TERMINAL_TYPES = (EventType.RUN_FINISHED, EventType.RUN_ERROR)


def _fail(rule: str, events: List[Any]) -> None:
    raise AssertionError(f"AG-UI protocol violation: {rule}\nstream was: {[event.type for event in events]}")


def _check_run_framing(events: List[Any]) -> None:
    types = [event.type for event in events]

    if not events:
        _fail("the stream carried no events at all", events)

    started = types.count(EventType.RUN_STARTED)
    if started > 1:
        _fail("RUN_STARTED appears more than once", events)
    if started == 1 and types[0] != EventType.RUN_STARTED:
        _fail("RUN_STARTED is not the first event", events)

    terminals = [index for index, event_type in enumerate(types) if event_type in TERMINAL_TYPES]
    if not terminals:
        _fail("the stream never reached RUN_FINISHED or RUN_ERROR", events)
    if len(terminals) > 1:
        _fail("the stream carries more than one terminal event", events)
    if terminals[0] != len(types) - 1:
        _fail(f"{types[terminals[0]]} is not the last event", events)


def _check_step_spans(events: List[Any]) -> None:
    active: List[str] = []
    for event in events:
        if event.type == EventType.STEP_STARTED:
            if event.step_name in active:
                _fail(f'step "{event.step_name}" is started while already active', events)
            active.append(event.step_name)
        elif event.type == EventType.STEP_FINISHED:
            if event.step_name not in active:
                _fail(f'step "{event.step_name}" is finished while not active', events)
            active.remove(event.step_name)
        elif event.type in TERMINAL_TYPES and active:
            _fail(f"steps {active} are still open at the terminal event", events)


def _check_text_messages(events: List[Any]) -> None:
    open_id: Optional[str] = None
    opened_at = -1
    content_seen = False
    for index, event in enumerate(events):
        if event.type == EventType.TEXT_MESSAGE_START:
            if open_id is not None:
                _fail(f"message {event.message_id} starts while message {open_id} is still open", events)
            open_id = event.message_id
            opened_at = index
            content_seen = False
        elif event.type == EventType.TEXT_MESSAGE_CONTENT:
            if open_id is None:
                _fail(f"content for message {event.message_id} arrives outside a message", events)
            if event.message_id != open_id:
                _fail(f"content for message {event.message_id} arrives inside message {open_id}", events)
            content_seen = True
        elif event.type == EventType.TEXT_MESSAGE_END:
            if open_id is None:
                _fail(f"message {event.message_id} ends without having started", events)
            if event.message_id != open_id:
                _fail(f"message {event.message_id} ends while message {open_id} is open", events)
            if not content_seen and index != opened_at + 1:
                _fail(
                    f"message {open_id} carries no content and is closed only after other events went out",
                    events,
                )
            open_id = None
        elif event.type in TERMINAL_TYPES and open_id is not None:
            _fail(f"message {open_id} is still open at the terminal event", events)


def _check_tool_calls(events: List[Any]) -> None:
    open_id: Optional[str] = None
    closed: List[str] = []
    resulted: List[str] = []
    seen: List[str] = []
    for event in events:
        if event.type == EventType.TOOL_CALL_START:
            if open_id is not None:
                _fail(f"tool call {event.tool_call_id} starts while tool call {open_id} is still open", events)
            if event.tool_call_id in seen:
                _fail(f"tool call id {event.tool_call_id} is started twice in one stream", events)
            open_id = event.tool_call_id
            seen.append(event.tool_call_id)
        elif event.type == EventType.TOOL_CALL_ARGS:
            if open_id is None:
                _fail(f"arguments for tool call {event.tool_call_id} arrive outside a tool call", events)
            if event.tool_call_id != open_id:
                _fail(f"arguments for tool call {event.tool_call_id} arrive inside tool call {open_id}", events)
        elif event.type == EventType.TOOL_CALL_END:
            if open_id is None:
                _fail(f"tool call {event.tool_call_id} ends without having started", events)
            if event.tool_call_id != open_id:
                _fail(f"tool call {event.tool_call_id} ends while tool call {open_id} is open", events)
            closed.append(open_id)
            open_id = None
        elif event.type == EventType.TOOL_CALL_RESULT:
            if event.tool_call_id in resulted:
                _fail(f"a second result arrives for tool call {event.tool_call_id}", events)
            if event.tool_call_id not in closed:
                _fail(f"a result arrives for tool call {event.tool_call_id}, which never ended", events)
            resulted.append(event.tool_call_id)
        elif event.type in TERMINAL_TYPES and open_id is not None:
            _fail(f"tool call {open_id} is still open at the terminal event", events)


def _check_tool_call_arguments(events: List[Any]) -> None:
    """A tool call's arguments have to arrive as the object that renders it.

    The client reads the deltas of one call as a single JSON document and hands it to
    whatever renders the call, which reads an argument list as an object. A call made
    without any arguments is therefore an empty object; a null is the absence of a
    document rather than a document saying nothing, and the render has no keys to read
    off it. The deltas are concatenated before being read, because a call whose
    arguments arrive in pieces is only a document once all of them have.
    """
    deltas: Dict[str, str] = {}
    order: List[str] = []
    for event in events:
        if event.type != EventType.TOOL_CALL_ARGS:
            continue
        if event.tool_call_id not in deltas:
            deltas[event.tool_call_id] = ""
            order.append(event.tool_call_id)
        deltas[event.tool_call_id] += event.delta

    for tool_call_id in order:
        raw = deltas[tool_call_id]
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError:
            _fail(f"the arguments of tool call {tool_call_id} are not valid JSON: {raw!r}", events)
            continue
        if not isinstance(arguments, dict):
            _fail(
                f"the arguments of tool call {tool_call_id} arrive as {raw!r}, which is not the object a render reads",
                events,
            )


def assert_valid_agui_stream(events: List[Any]) -> None:
    """Assert an emitted event list is free of the framing faults documented above."""
    _check_run_framing(events)
    _check_step_spans(events)
    _check_text_messages(events)
    _check_tool_calls(events)
    _check_tool_call_arguments(events)
