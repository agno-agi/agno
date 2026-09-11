"""The shared SSE parser is what makes every absence assertion in this directory sound.

If it can return an empty list, a body that was never a stream reads the same as a run
that emitted no such event, and the suites above pass without having seen anything. The
same goes for a frame it hands on in a shape no assertion can read. These tests pin
those properties down; they need no model and no network.

The protocol and spelling checks the served-run suite applies are covered here too,
since a check that passes everything would leave that suite asserting nothing.
"""

import importlib.util

import pytest

from ._agui_sse import assert_event_absent, assert_valid_wire_stream, get_event_types, parse_sse_events

requires_ag_ui = pytest.mark.skipif(importlib.util.find_spec("ag_ui") is None, reason="ag_ui not installed")

DEAD_BODIES = [
    pytest.param("", id="empty body"),
    pytest.param("   \n\n  \n", id="whitespace only"),
    pytest.param("<html><body>500 Internal Server Error</body></html>", id="error page"),
    pytest.param("upstream connect error or disconnect/reset before headers", id="proxy error"),
    pytest.param(": keep-alive\n\n", id="comment frames only"),
    pytest.param("data:\n\n", id="keep-alive frames only"),
    pytest.param('data: {"type": "RUN_STARTED"}', id="a single frame that was never terminated"),
]


@pytest.mark.parametrize("body", DEAD_BODIES)
def test_a_body_that_carries_no_frame_is_refused(body):
    with pytest.raises(AssertionError, match="no data frames"):
        parse_sse_events(body)


@pytest.mark.parametrize("body", DEAD_BODIES)
def test_an_absence_assertion_on_a_dead_body_cannot_pass(body):
    # The vacuous pass this guards: `event_type not in types` is true of a stream that
    # never ran. The parser has to be the thing that stops it, because an absence check
    # can be written inline without going through assert_event_absent.
    with pytest.raises(AssertionError):
        assert "RUN_ERROR" not in get_event_types(parse_sse_events(body))


def test_a_frame_split_across_several_data_lines_parses():
    body = 'data: {"type":\ndata: "RUN_STARTED",\ndata: "threadId": "t"}\n\n'

    assert parse_sse_events(body) == [{"type": "RUN_STARTED", "threadId": "t"}]


def test_frames_are_kept_separate_and_crlf_framing_reads_the_same():
    body = 'data: {"type": "RUN_STARTED"}\r\n\r\ndata: {"type": "RUN_FINISHED"}\r\n\r\n'

    assert get_event_types(parse_sse_events(body)) == ["RUN_STARTED", "RUN_FINISHED"]


def test_a_line_of_spaces_does_not_end_a_frame():
    """SSE ends a frame at an empty line. A line of spaces is a field name with no
    colon, which is ignored, so treating it as a boundary splits one payload in two."""
    body = 'data: {"type":\n   \ndata: "RUN_STARTED"}\n\n'

    assert parse_sse_events(body) == [{"type": "RUN_STARTED"}]


def test_an_indented_data_prefix_is_not_a_data_line():
    """``   data: ...`` names the field ``   data``, which SSE ignores. Reading it as
    data accepts a body the browser would take as carrying no event at all."""
    body = '   data: {"type": "RUN_STARTED"}\n\n'

    with pytest.raises(AssertionError, match="no data frames"):
        parse_sse_events(body)


@pytest.mark.parametrize("keep_alive", ["data:\n\n", "data: \n\n", ": ping\n\n"], ids=["bare", "padded", "comment"])
def test_a_keep_alive_between_frames_is_not_a_malformed_stream(keep_alive):
    """A frame whose data buffer is empty is never dispatched, so it is not an event
    and not a parse failure either."""
    body = f'data: {{"type": "RUN_STARTED"}}\n\n{keep_alive}data: {{"type": "RUN_FINISHED"}}\n\n'

    assert get_event_types(parse_sse_events(body)) == ["RUN_STARTED", "RUN_FINISHED"]


def test_a_stream_cut_after_its_terminal_line_cannot_satisfy_the_absence_gate():
    """A cut connection leaves the last block with no empty line to end it.

    The browser discards an unterminated block, and reading one here would hand a
    truncated run the RUN_FINISHED that assert_event_absent treats as proof the run
    reached its end, which is the vacuous pass this file exists to rule out.
    """
    body = 'data: {"type": "RUN_STARTED"}\n\ndata: {"type": "RUN_FINISHED"}'

    types = get_event_types(parse_sse_events(body))

    assert types == ["RUN_STARTED"]
    with pytest.raises(AssertionError, match="never finished"):
        assert_event_absent(types, "STATE_DELTA")


def test_a_stream_cut_inside_its_last_payload_is_not_read_as_an_event():
    """The same cut a line earlier: the fragment must not be parsed or reported as JSON."""
    body = 'data: {"type": "RUN_STARTED"}\n\ndata: {"type": "RUN_FINIS'

    assert get_event_types(parse_sse_events(body)) == ["RUN_STARTED"]


def test_a_payload_that_is_not_json_is_refused():
    body = 'data: {"type": "RUN_STARTED"}\n\ndata: not-json\n\n'

    with pytest.raises(AssertionError, match="not valid JSON"):
        parse_sse_events(body)


@pytest.mark.parametrize(
    "payload", ['"a string"', "42", "null", "true", "[1, 2]"], ids=["string", "number", "null", "bool", "array"]
)
def test_a_payload_that_is_valid_json_but_not_an_object_is_refused(payload):
    """Handing one on surfaces as an attribute error several frames later, naming
    nothing about the body that caused it."""
    with pytest.raises(AssertionError, match="not a JSON object"):
        parse_sse_events(f"data: {payload}\n\n")


def test_a_frame_without_a_type_is_refused():
    """No assertion in these suites can match a typeless frame, so letting one through
    quietly shortens the stream that the presence and absence checks read."""
    with pytest.raises(AssertionError, match="carries no type"):
        get_event_types(parse_sse_events('data: {"threadId": "t"}\n\n'))


def test_absence_needs_a_stream_that_started():
    with pytest.raises(AssertionError, match="never started"):
        assert_event_absent(["RUN_FINISHED"], "STATE_DELTA")


def test_absence_needs_a_run_that_finished():
    """The route can fail before RUN_STARTED is yielded or after it, so a start is not
    evidence the run got far enough for the absence to mean anything."""
    with pytest.raises(AssertionError, match="never finished"):
        assert_event_absent(["RUN_STARTED", "RUN_ERROR"], "STATE_DELTA")

    assert_event_absent(["RUN_STARTED", "RUN_FINISHED"], "STATE_DELTA")


def wire_run(*body):
    return [
        {"type": "RUN_STARTED", "threadId": "t", "runId": "r"},
        *body,
        {"type": "RUN_FINISHED", "threadId": "t", "runId": "r"},
    ]


@requires_ag_ui
def test_a_well_formed_wire_stream_passes_the_protocol_check():
    assert_valid_wire_stream(
        wire_run(
            {"type": "STEP_STARTED", "stepName": "Greet"},
            {"type": "TEXT_MESSAGE_START", "messageId": "m1", "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "hi"},
            {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
            {"type": "STEP_FINISHED", "stepName": "Greet"},
        )
    )


@requires_ag_ui
def test_a_wire_stream_leaving_a_step_open_is_refused():
    with pytest.raises(AssertionError, match="still open at the terminal event"):
        assert_valid_wire_stream(wire_run({"type": "STEP_STARTED", "stepName": "Greet"}))


@requires_ag_ui
def test_a_wire_stream_leaving_a_tool_call_open_is_refused():
    with pytest.raises(AssertionError, match="still open at the terminal event"):
        assert_valid_wire_stream(wire_run({"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "lookup"}))


@requires_ag_ui
def test_a_misspelled_field_name_on_the_wire_is_refused():
    """The protocol models allow extra fields, so this validates cleanly on its own."""
    with pytest.raises(AssertionError, match=r"\['mesageId'\]"):
        assert_valid_wire_stream(
            wire_run(
                {"type": "TEXT_MESSAGE_START", "mesageId": "m1", "messageId": "m1", "role": "assistant"},
                {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "hi"},
                {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
            )
        )


@requires_ag_ui
def test_a_field_left_in_snake_case_on_the_wire_is_refused():
    """The models accept the snake_case spelling of every field, so this validates
    cleanly too, while the browser reads the camelCase key and finds nothing."""
    with pytest.raises(AssertionError, match=r"\['message_id'\]"):
        assert_valid_wire_stream(
            wire_run(
                {"type": "TEXT_MESSAGE_START", "message_id": "m1", "role": "assistant"},
                {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "hi"},
                {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
            )
        )


@requires_ag_ui
def test_an_undeclared_key_on_the_wire_is_refused():
    with pytest.raises(AssertionError, match=r"\['totallyMadeUp'\]"):
        assert_valid_wire_stream(wire_run({"type": "STEP_STARTED", "stepName": "Greet", "totallyMadeUp": 1}))
