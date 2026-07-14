"""
Unit tests for synchronous trace_id propagation onto run outputs and events.

The trace_id is captured from the active OTel span at run start (inside the
instrumented run functions) and propagated to every streamed event via
handle_event(), so clients can correlate runs with traces in real time
without querying the database.
"""

from opentelemetry.sdk.trace import TracerProvider

from agno.run.agent import RunOutput, RunStartedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput, WorkflowStartedEvent
from agno.utils.events import handle_event
from agno.utils.otel import get_current_trace_id

TRACE_ID_HEX_LENGTH = 32


def _local_tracer():
    """A private tracer whose spans do not touch the global provider."""
    return TracerProvider().get_tracer("test")


def test_get_current_trace_id_returns_none_outside_span():
    assert get_current_trace_id() is None


def test_get_current_trace_id_inside_span():
    tracer = _local_tracer()
    with tracer.start_as_current_span("run") as span:
        trace_id = get_current_trace_id()

    assert trace_id == format(span.get_span_context().trace_id, "032x")
    assert len(trace_id) == TRACE_ID_HEX_LENGTH


def test_run_outputs_accept_trace_id():
    trace_id = "0" * 31 + "1"
    assert RunOutput(trace_id=trace_id).trace_id == trace_id
    assert TeamRunOutput(trace_id=trace_id).trace_id == trace_id
    assert WorkflowRunOutput(trace_id=trace_id).trace_id == trace_id


def test_run_output_serializes_trace_id():
    trace_id = "ab" * 16
    output = RunOutput(run_id="run_1", trace_id=trace_id)

    as_dict = output.to_dict()
    assert as_dict["trace_id"] == trace_id

    restored = RunOutput.from_dict(as_dict)
    assert restored.trace_id == trace_id


def test_run_output_without_trace_id_omits_field():
    assert "trace_id" not in RunOutput(run_id="run_1").to_dict()


def test_event_serializes_trace_id():
    trace_id = "cd" * 16
    event = RunStartedEvent(run_id="run_1", trace_id=trace_id)

    as_dict = event.to_dict()
    assert as_dict["trace_id"] == trace_id

    restored = RunStartedEvent.from_dict(as_dict)
    assert restored.trace_id == trace_id


def test_handle_event_stamps_trace_id_from_run_response():
    trace_id = "ef" * 16
    run_response = RunOutput(run_id="run_1", trace_id=trace_id)
    event = RunStartedEvent(run_id="run_1")

    handled = handle_event(event, run_response)

    assert handled.trace_id == trace_id


def test_handle_event_does_not_overwrite_existing_trace_id():
    run_response = RunOutput(run_id="run_1", trace_id="aa" * 16)
    event = RunStartedEvent(run_id="run_1", trace_id="bb" * 16)

    handled = handle_event(event, run_response)

    assert handled.trace_id == "bb" * 16


def test_handle_event_with_no_trace_id_leaves_event_unset():
    run_response = RunOutput(run_id="run_1")
    event = RunStartedEvent(run_id="run_1")

    handled = handle_event(event, run_response)

    assert handled.trace_id is None


def test_handle_event_stamps_team_events():
    trace_id = "12" * 16
    run_response = TeamRunOutput(run_id="run_1", trace_id=trace_id)
    event = TeamRunContentEvent(run_id="run_1")

    handled = handle_event(event, run_response)

    assert handled.trace_id == trace_id


def test_workflow_event_accepts_trace_id():
    trace_id = "34" * 16
    event = WorkflowStartedEvent(run_id="run_1", trace_id=trace_id)

    assert event.to_dict()["trace_id"] == trace_id
