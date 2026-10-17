"""SSE helpers shared by the AG-UI interface integration tests.

Every AG-UI suite reads the same event stream off the same endpoint and then asserts
that some event is absent. That assertion is only sound if the parser refuses to skip
a payload it cannot read, so the strictness below has to hold for all of them at once.
One copy is what keeps it that way.
"""

import json
from typing import Any, Dict, Iterator, List

DATA_PREFIX = "data:"


def _iter_frame_payloads(content: str) -> Iterator[str]:
    """Yield one payload per SSE frame.

    A frame ends at an empty line and may carry several ``data:`` lines, which SSE
    joins with a newline into a single payload. Reading each line as its own event
    turns a legal reframing of the same stream into a parse failure.

    Only a genuinely empty line ends a frame, and only a line whose first characters
    are the field name counts as data. A line of spaces and a line that indents the
    prefix are both something other than what they look like, and reading them as a
    frame boundary or as data would let a body the browser reads one way be read
    another way here. A ``data`` line with no colon is the one shape read differently:
    SSE would take it as the field with an empty value, and it is dropped here as an
    unknown field, which the AG-UI encoder never emits.

    A frame whose payload comes out empty is not dispatched, which is how a keep-alive
    carrying no payload stays a keep-alive. Nor is a trailing block that never met an
    empty line: the browser discards an unterminated block, and dispatching it here
    would let a body cut off mid-stream hand its last complete line to an assertion
    that only means something on a run which reached the end.
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    data_lines: List[str] = []
    for line in normalized.split("\n"):
        if not line:
            payload = "\n".join(data_lines)
            data_lines = []
            if payload:
                yield payload
            continue
        if line.startswith(DATA_PREFIX):
            value = line[len(DATA_PREFIX) :]
            # SSE strips one leading space from a field value, not every one.
            data_lines.append(value[1:] if value.startswith(" ") else value)


def parse_sse_events(content: str) -> List[Dict[str, Any]]:
    """Parse an SSE body into events, refusing to return nothing.

    Returning an empty list for a body that carries no frame is what makes an
    absence assertion vacuous: an empty body, an error page and a stream that was
    never read all come back looking like a run that simply emitted no such event.
    An AG-UI run that reached the route's generator at all emits at least one event,
    so a body with no frame in it is reported here, with the body quoted, rather
    than handed on as a result.

    A payload that parses as valid JSON but is not an object is reported the same
    way. The return type says these are events, and every caller reads them as
    mappings; handing one on would surface as an attribute error several frames
    later, naming nothing about the body that caused it.
    """
    events: List[Dict[str, Any]] = []
    for payload in _iter_frame_payloads(content):
        try:
            event = json.loads(payload)
        except json.JSONDecodeError as error:
            raise AssertionError(f"SSE data frame is not valid JSON: {payload!r}") from error
        if not isinstance(event, dict):
            raise AssertionError(f"SSE data frame is not a JSON object, so it is not an event: {payload!r}")
        events.append(event)
    if not events:
        raise AssertionError(f"SSE body carried no data frames, so nothing about the stream was observed: {content!r}")
    return events


def get_event_types(events: List[Dict[str, Any]]) -> List[str]:
    """Read the type off every event, refusing a frame that has none.

    A frame with no type cannot be matched by any assertion written against these
    names, so returning a None in its place quietly shortens the stream that the
    presence and absence assertions are reading.
    """
    types: List[str] = []
    for event in events:
        event_type = event.get("type")
        if not isinstance(event_type, str):
            raise AssertionError(f"SSE event carries no type, so nothing can be asserted about it: {event!r}")
        types.append(event_type)
    return types


def assert_event_absent(types: List[str], event_type: str) -> None:
    """Assert an event is missing from a stream that ran to completion.

    ``event_type not in types`` on its own passes for the wrong reason whenever the
    stream never got going. A streaming response commits its 200 and its headers
    before the generator runs, so a body carrying nothing but a failure still arrives
    as a success, and a run that failed on its first event carries no more than the
    error. RUN_STARTED alone does not rule that out either: the route can fail before
    it is yielded, leaving RUN_ERROR alone, or after it, leaving RUN_STARTED then
    RUN_ERROR. The bar is therefore the run reaching RUN_FINISHED: absence means
    something only once the run that would have emitted the event got to the end.
    """
    assert types, f"the stream carried no events, so the absence of {event_type} proves nothing"
    assert "RUN_STARTED" in types, f"the stream never started, so the absence of {event_type} proves nothing: {types}"
    assert "RUN_FINISHED" in types, (
        f"the run never finished, so the absence of {event_type} proves nothing about a run that did: {types}"
    )
    assert event_type not in types, f"expected no {event_type} in the stream: {types}"


def assert_valid_wire_stream(events: List[Dict[str, Any]]) -> None:
    """Check a served stream against the same framing rules the mapper suites use.

    A run driven by the real engine over HTTP is the stream most worth checking and the
    one no hand-built chunk list can stand in for. The rules themselves live with the
    mapper suites that already apply them; importing them keeps one statement of what
    the client will accept rather than a second copy that drifts.

    Field spelling is checked here rather than left to the parse. The protocol models
    allow extra fields and accept the snake_case spelling of every one of them, so a
    payload that misspells a name or sends it unconverted validates cleanly and the
    parse says nothing at all about what went over the wire. What the browser reads is
    the camelCase key, so every key on the wire has to be one the model declares under
    that name.
    """
    # Imported here, not at module scope: the parser above is what the SSE tests import,
    # and they must keep collecting on an install without ag_ui.
    from ag_ui.core import Event
    from pydantic import TypeAdapter

    from tests.unit.os.interfaces._agui_stream_rules import assert_valid_agui_stream

    adapter = TypeAdapter(Event)
    parsed = []
    for event in events:
        model = adapter.validate_python(event)
        declared = {field.alias or name for name, field in type(model).model_fields.items()}
        unknown = sorted(set(event) - declared)
        assert not unknown, (
            f"{event.get('type')} carries {unknown} on the wire, which {type(model).__name__} does not declare "
            f"under those names: {event!r}"
        )
        parsed.append(model)
    assert_valid_agui_stream(parsed)


def make_request_body(
    message: str, state: Any = None, thread_id: str = "test-thread", run_id: str = "test-run"
) -> Dict[str, Any]:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": state,
        "messages": [{"id": "msg-1", "role": "user", "content": message}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
