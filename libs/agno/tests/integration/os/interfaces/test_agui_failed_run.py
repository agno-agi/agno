"""What the AG-UI route serves when a run fails part way through.

A run that fails is the one case where the terminal event is written by the route rather
than by the mapper, and the route sees only the exception: the spans the client is
holding open are known to the mapper alone. So this is checked on the served body rather
than on a mapper's return value, because it is the seam between the two that decides
whether the stream the browser gets is one it will accept.

The engine turns a failing workflow step into a completed run, so the failure here is
raised by the entity's own stream, which is what an entity that dies mid-run does.
"""

import threading

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from agno.run.agent import RunCompletedEvent, RunContentEvent
from agno.run.workflow import StepStartedEvent

from ._agui_sse import assert_valid_wire_stream, get_event_types, make_request_body, parse_sse_events

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from agno.os.interfaces.agui.router import attach_routes  # noqa: E402

pytestmark = pytest.mark.integration


class FailsPartWayThroughEntity:
    """An entity whose run opens a step, streams into it, and then dies."""

    db = None

    async def arun(self, **kwargs):
        yield StepStartedEvent(step_name="Gather", step_id="gather")
        yield RunContentEvent(content="half an answer", step_id="gather")
        raise RuntimeError("the executor blew up")


@pytest.fixture(scope="module")
def response():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(attach_routes(APIRouter(), agent=FailsPartWayThroughEntity()))  # type: ignore[arg-type]
    with TestClient(app) as client:
        return client.post("/agui", json=make_request_body("Say hello"))


@pytest.fixture(scope="module")
def events(response):
    return parse_sse_events(response.text)


def test_a_failed_run_is_served_as_an_error_the_client_can_reach(response, events):
    # A streaming response commits its 200 before the generator runs, so the status says
    # nothing about the run; the terminal event is what the client reads the failure off.
    assert response.status_code == 200

    types = get_event_types(events)

    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_ERROR"
    assert events[-1]["message"] == "the executor blew up"


def test_the_served_stream_of_a_failed_run_obeys_the_protocol_framing_rules(events):
    """Without this, a mid-run failure serves a stream the client aborts on."""
    assert_valid_wire_stream(events)


def test_the_step_the_run_died_inside_is_finished_before_the_error(events):
    types = get_event_types(events)

    assert types.index("STEP_FINISHED") < types.index("RUN_ERROR")
    assert types.index("TEXT_MESSAGE_END") < types.index("RUN_ERROR")


class CompletesWithAnUncopyableStateEntity:
    """An entity that opens a step and then completes carrying a state nothing can copy.

    The completion is built as one batch: the open spans are closed at the top of it and
    the final state is serialized at the bottom. A state the copy cannot walk therefore
    fails the whole batch after the closings were already drained out of the mapper's
    state, which is the seam this scenario exists to hold.
    """

    db = None

    async def arun(self, **kwargs):
        yield StepStartedEvent(step_name="Gather", step_id="gather")
        yield RunContentEvent(content="half an answer", step_id="gather")
        yield RunCompletedEvent(content="done", session_state={"seen": 2, "guard": threading.Lock()})


@pytest.fixture(scope="module")
def uncopyable_state_events():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(
        attach_routes(APIRouter(), agent=CompletesWithAnUncopyableStateEntity())  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        response = client.post("/agui", json=make_request_body("Say hello", state={"seen": 1}))
    return parse_sse_events(response.text)


def test_a_run_whose_state_cannot_be_copied_serves_a_stream_the_client_accepts(uncopyable_state_events):
    """Without this, the step opened mid-run is never finished and the client aborts."""
    assert_valid_wire_stream(uncopyable_state_events)


def test_a_run_whose_state_cannot_be_copied_closes_its_step_and_reports_the_failure(uncopyable_state_events):
    """The state the client never received is the reason the run is reported as failed.

    Ending on a success instead would hand the reader a finished turn whose state quietly
    stayed behind, which is worse than an error they can see.
    """
    types = get_event_types(uncopyable_state_events)

    assert types[-1] == "RUN_ERROR"
    assert "RUN_FINISHED" not in types
    assert types.index("STEP_FINISHED") < types.index("RUN_ERROR")
    assert types.index("TEXT_MESSAGE_END") < types.index("RUN_ERROR")
