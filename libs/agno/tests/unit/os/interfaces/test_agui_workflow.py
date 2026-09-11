import inspect
import logging
from datetime import datetime
from unittest.mock import MagicMock

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import EventType
from ag_ui.core.types import Tool as AGUITool
from pydantic import BaseModel

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.os.interfaces.agui import router as agui_router
from agno.os.interfaces.agui.agui import AGUI
from agno.os.interfaces.agui.handlers import _iter_step_results, on_run_content
from agno.os.interfaces.agui.router import attach_routes, run_entity
from agno.os.interfaces.agui.state import SpanTransition, StepSpan, StreamState
from agno.os.interfaces.agui.stream import stream_agno_response_as_agui_events
from agno.run.agent import RunCancelledEvent as AgentRunCancelledEvent
from agno.run.agent import RunContentEvent
from agno.run.agent import RunErrorEvent as AgentRunErrorEvent
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.base import RunStatus
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.workflow import (
    RouterPausedEvent,
    StepCompletedEvent,
    StepErrorEvent,
    StepExecutorPausedEvent,
    StepOutputReviewEvent,
    StepPausedEvent,
    StepStartedEvent,
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    WorkflowPausedEvent,
    WorkflowRunEvent,
    WorkflowStartedEvent,
)
from agno.workflow.remote import RemoteWorkflow
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnReject, StepInput, StepOutput
from agno.workflow.workflow import Workflow

from ._agui_mappers import (
    MAPPER_DRIVERS,
    MAPPER_IDS,
    drain_async_mapper,
    drive_sync_mapper,
    validated,
)
from ._agui_stream_rules import assert_valid_agui_stream


def echo_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content=str(step_input.input or ""))


def exploding_step(step_input: StepInput) -> StepOutput:
    raise ValueError("step exploded")


def build_workflow() -> Workflow:
    return Workflow(id="test-workflow", name="Test Workflow", steps=[Step(name="Echo", executor=echo_step)])


def build_cancel_on_reject_workflow() -> Workflow:
    """A workflow the engine cancels for real once its review gate is rejected."""
    return Workflow(
        id="cancel-workflow",
        name="Cancel Workflow",
        db=InMemoryDb(),
        telemetry=False,
        steps=[
            Step(
                name="Gate",
                executor=echo_step,
                human_review=HumanReview(requires_confirmation=True, on_reject=OnReject.cancel),
            )
        ],
    )


class FakeRunInput:
    def __init__(self, *, context=None, state=None, tools=None, messages=None):
        self.messages = messages if messages is not None else [MagicMock(role="user", content="test")]
        self.thread_id = "test-thread"
        self.run_id = "test-run"
        self.forwarded_props = None
        self.state = state
        self.context = context
        self.tools = tools


def build_remote_workflow() -> RemoteWorkflow:
    return RemoteWorkflow(base_url="http://localhost:9999", workflow_id="remote-workflow")


def capture_arun(entity) -> dict:
    """Replace an entity's arun with a no-op that records the kwargs it was called with."""
    captured: dict = {}

    async def arun(**kwargs):
        captured.update(kwargs)
        return
        yield

    entity.arun = arun  # type: ignore[method-assign]
    return captured


async def collect_events(entity, run_input) -> list:
    """Drain a run, failing if it ended in RUN_ERROR.

    run_entity turns any exception into a RUN_ERROR event rather than raising, so a
    routing test that discards its events stays green even when the run never happened.
    """
    events = [event async for event in run_entity(entity, run_input)]
    errors = [event.message for event in events if event.type == EventType.RUN_ERROR]
    assert not errors, f"run ended in RUN_ERROR: {errors}"
    assert_valid_agui_stream(events)
    return events


@pytest.fixture(params=MAPPER_DRIVERS, ids=MAPPER_IDS)
def run_stream(request):
    """Drive one chunk sequence through a mapper, once per mapper.

    A failure is reported under the sync_mapper or async_mapper id of the mapper that
    produced it.
    """
    return validated(request.param)


def event_types(events):
    return [event.type for event in events]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_agui_accepts_a_workflow():
    workflow = build_workflow()
    interface = AGUI(workflow=workflow)

    assert interface.workflow is workflow
    assert interface.get_router() is not None


def test_agui_without_any_entity_is_rejected():
    with pytest.raises(ValueError, match="requires an agent, team, or workflow"):
        AGUI()


def test_agui_scope_mapping_for_a_workflow():
    interface = AGUI(workflow=build_workflow(), prefix="/flow")

    assert interface.get_scope_mappings() == {"POST /flow/agui": ["workflows:run"]}


def test_agui_scope_mapping_prefers_agent_over_workflow():
    interface = AGUI(agent=MagicMock(), workflow=build_workflow())

    assert interface.get_scope_mappings() == {"POST /agui": ["agents:run"]}


def test_attach_routes_accepts_a_workflow():
    from fastapi.routing import APIRouter

    router = attach_routes(router=APIRouter(), workflow=build_workflow())

    assert {route.path for route in router.routes} == {"/agui", "/status"}


def test_attach_routes_without_any_entity_is_rejected():
    from fastapi.routing import APIRouter

    with pytest.raises(ValueError, match="Either agent, team or workflow must be provided."):
        attach_routes(router=APIRouter())


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_run_receives_session_state_and_not_a_run_context():
    workflow = build_workflow()
    captured = capture_arun(workflow)

    await collect_events(workflow, FakeRunInput(state={"count": 1}))

    assert captured["input"] == "test"
    assert captured["session_state"] == {"count": 1}
    assert captured["stream"] is True
    assert captured["stream_events"] is True
    assert "run_context" not in captured


@pytest.mark.asyncio
async def test_workflow_run_receives_agui_context_as_dependencies():
    workflow = build_workflow()
    captured = capture_arun(workflow)
    context = [MagicMock(description="user_name", value="Alice")]

    await collect_events(workflow, FakeRunInput(context=context))

    assert captured["dependencies"] == {"user_name": "Alice"}
    assert captured["add_dependencies_to_context"] is True


@pytest.mark.asyncio
async def test_client_tools_are_dropped_for_a_workflow(caplog):
    """An agent receives this definition as a client tool; a workflow must get it under no kwarg."""
    tool = AGUITool(name="change_background", description="Change it", parameters={"type": "object"})

    agent = Agent(id="control-agent", name="Control")
    agent_captured = capture_arun(agent)
    await collect_events(agent, FakeRunInput(tools=[tool]))
    assert [fn.name for fn in agent_captured["run_context"].client_tools] == ["change_background"]

    workflow = build_workflow()
    captured = capture_arun(workflow)
    with caplog.at_level(logging.WARNING):
        await collect_events(workflow, FakeRunInput(tools=[tool]))

    assert "client_tools" not in captured
    assert not any("change_background" in repr(value) for value in captured.values())
    assert "not forwarded to workflows" in caplog.text


@pytest.mark.asyncio
async def test_trailing_tool_messages_do_not_resume_a_workflow(monkeypatch):
    """A workflow has no external-execution pause, so a tool message must start a fresh run."""
    workflow = build_workflow()
    captured = capture_arun(workflow)

    async def refuse_resume(**kwargs):
        raise AssertionError("the workflow was routed to the resume path")

    monkeypatch.setattr(agui_router, "resume_paused_run", refuse_resume)

    messages = [
        MagicMock(role="user", content="run it"),
        MagicMock(role="tool", tool_call_id="call-1", content="done", error=None),
    ]

    await collect_events(workflow, FakeRunInput(messages=messages))

    assert captured["input"] == "run it"
    assert captured["stream"] is True


@pytest.mark.asyncio
async def test_a_discarded_workflow_resume_says_the_run_starts_over(monkeypatch, caplog):
    """Trailing tool messages are a client answering a pause, and a workflow cannot take one.

    The request is dropped and the workflow runs again from its first step against the
    same user message, repeating every side effect the earlier run had. Saying so is the
    part a reader needs: the client is told nothing, and sees an ordinary run it never
    asked for.
    """
    workflow = build_workflow()
    capture_arun(workflow)

    async def refuse_resume(**kwargs):
        raise AssertionError("the workflow was routed to the resume path")

    monkeypatch.setattr(agui_router, "resume_paused_run", refuse_resume)

    messages = [
        MagicMock(role="user", content="run it"),
        MagicMock(role="tool", tool_call_id="call-1", content="done", error=None),
    ]

    with caplog.at_level(logging.WARNING):
        await collect_events(workflow, FakeRunInput(messages=messages))

    assert "re-run from the start" in caplog.text


@pytest.mark.asyncio
async def test_a_remote_workflow_reports_the_context_it_cannot_forward(caplog):
    """The client's context has nowhere to go on a remote workflow, so it is dropped.

    Every other kwarg dropped on this path says so; this one left the client's own
    per-run context to vanish without a line to find it by.
    """
    remote = build_remote_workflow()
    captured = capture_arun(remote)
    context = [MagicMock(description="user_name", value="Alice")]

    with caplog.at_level(logging.WARNING):
        await collect_events(remote, FakeRunInput(context=context))

    assert "dependencies" not in captured
    assert "not forwarded to remote workflows" in caplog.text


@pytest.mark.asyncio
async def test_a_remote_workflow_without_context_reports_nothing(caplog):
    """The line names a drop, so a run with nothing to drop must not emit it."""
    remote = build_remote_workflow()
    capture_arun(remote)

    with caplog.at_level(logging.WARNING):
        await collect_events(remote, FakeRunInput(state={"count": 1}))

    assert "not forwarded to remote workflows" not in caplog.text


@pytest.mark.asyncio
async def test_a_remote_workflow_receives_only_wire_fields_its_arun_declares():
    """RemoteWorkflow.arun forwards unrecognised kwargs to the remote server as form
    fields, so dependency kwargs meant for an in-process workflow must not be sent."""
    remote = build_remote_workflow()
    captured = capture_arun(remote)
    context = [MagicMock(description="user_name", value="Alice")]

    await collect_events(remote, FakeRunInput(context=context, state={"count": 1}))

    assert captured["session_state"] == {"count": 1}
    assert "dependencies" not in captured
    assert "add_dependencies_to_context" not in captured
    assert "run_context" not in captured
    declared = set(inspect.signature(RemoteWorkflow.arun).parameters)
    assert set(captured) <= declared


# ---------------------------------------------------------------------------
# Event mapping
# ---------------------------------------------------------------------------


def test_step_spans_are_opened_and_closed(run_stream):
    events = run_stream(
        [
            WorkflowStartedEvent(),
            StepStartedEvent(step_name="Plan"),
            StepCompletedEvent(step_name="Plan", content="a plan"),
            WorkflowCompletedEvent(content="done"),
        ]
    )

    types = event_types(events)
    assert types.index(EventType.STEP_STARTED) < types.index(EventType.STEP_FINISHED)
    assert types[-1] == EventType.RUN_FINISHED

    started = [event for event in events if event.type == EventType.STEP_STARTED]
    finished = [event for event in events if event.type == EventType.STEP_FINISHED]
    assert [event.step_name for event in started] == ["Plan"]
    assert [event.step_name for event in finished] == ["Plan"]


def test_step_without_streamed_text_emits_its_output_as_a_message(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="Handoff"),
            StepCompletedEvent(step_name="Handoff", content="handed off"),
            WorkflowCompletedEvent(),
        ]
    )

    deltas = [event.delta for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT]
    assert deltas == ["handed off"]


def test_step_that_streamed_text_does_not_repeat_it(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="Plan", step_id="plan"),
            RunContentEvent(content="streamed ", step_id="plan", step_name="Plan"),
            RunContentEvent(content="answer", step_id="plan", step_name="Plan"),
            StepCompletedEvent(step_name="Plan", step_id="plan", content="streamed answer"),
            WorkflowCompletedEvent(),
        ]
    )

    deltas = [event.delta for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT]
    assert deltas == ["streamed ", "answer"]


def test_each_step_gets_its_own_message(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="One", step_id="one"),
            RunContentEvent(content="first", step_id="one", step_name="One"),
            StepCompletedEvent(step_name="One", step_id="one", content="first"),
            StepStartedEvent(step_name="Two", step_id="two"),
            RunContentEvent(content="second", step_id="two", step_name="Two"),
            StepCompletedEvent(step_name="Two", step_id="two", content="second"),
            WorkflowCompletedEvent(),
        ]
    )

    message_ids = {event.message_id for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT}
    assert len(message_ids) == 2


def test_a_step_name_is_never_opened_twice(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="Loop"),
            StepStartedEvent(step_name="Loop"),
            StepCompletedEvent(step_name="Loop", content="once"),
            WorkflowCompletedEvent(),
        ]
    )

    assert event_types(events).count(EventType.STEP_STARTED) == 1
    assert event_types(events).count(EventType.STEP_FINISHED) == 1


def test_a_step_left_open_is_closed_before_the_run_ends(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="Never finished"),
            WorkflowCompletedEvent(),
        ]
    )

    types = event_types(events)
    assert types.count(EventType.STEP_FINISHED) == 1
    assert types.index(EventType.STEP_FINISHED) < types.index(EventType.RUN_FINISHED)


def test_workflow_error_becomes_a_run_error_carrying_the_reason(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="Plan"),
            WorkflowErrorEvent(error="the step blew up", error_type="ValueError"),
        ]
    )

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message == "the step blew up"
    assert events[-1].code == "ValueError"
    assert EventType.RUN_FINISHED not in event_types(events)


def test_a_failed_step_result_ends_the_run_with_an_error(run_stream):
    """A workflow that gives up on a step still reports completion, so the failure lives on the payload."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Boom"),
            WorkflowCompletedEvent(
                content="Step skipped due to error: step exploded",
                step_results=[
                    StepOutput(
                        step_name="Boom",
                        content="Step skipped due to error: step exploded",
                        success=False,
                        error="step exploded",
                    )
                ],
            ),
        ]
    )

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message == "step exploded"
    assert EventType.RUN_FINISHED not in event_types(events)


def test_a_failed_step_result_closes_open_spans_before_the_error(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="Boom"),
            WorkflowCompletedEvent(
                step_results=[StepOutput(step_name="Boom", success=False, error="step exploded")],
            ),
        ]
    )

    types = event_types(events)
    assert types.index(EventType.STEP_FINISHED) < types.index(EventType.RUN_ERROR)


def test_a_nested_failed_step_result_ends_the_run_with_an_error(run_stream):
    """Parallel, loop and condition steps report their children under StepOutput.steps."""
    events = run_stream(
        [
            WorkflowCompletedEvent(
                step_results=[
                    StepOutput(
                        step_name="Par",
                        success=False,
                        steps=[
                            StepOutput(step_name="Ok", content="fine", success=True),
                            StepOutput(step_name="Boom", success=False, error="nested exploded"),
                        ],
                    )
                ],
            ),
        ]
    )

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message == "nested exploded"


def test_a_failed_step_result_without_an_error_message_still_ends_the_run_with_an_error(run_stream):
    events = run_stream([WorkflowCompletedEvent(step_results=[StepOutput(step_name="Boom", success=False)])])

    assert events[-1].type == EventType.RUN_ERROR
    assert "Boom" in events[-1].message


def test_successful_step_results_still_finish_the_run(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="Plan"),
            StepCompletedEvent(step_name="Plan", content="a plan"),
            WorkflowCompletedEvent(
                content="a plan",
                step_results=[
                    StepOutput(
                        step_name="Plan",
                        content="a plan",
                        steps=[StepOutput(step_name="Inner", content="inner", success=True)],
                    )
                ],
            ),
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    assert EventType.RUN_ERROR not in event_types(events)


@pytest.mark.asyncio
async def test_a_workflow_whose_step_raises_streams_a_run_error():
    workflow = Workflow(
        id="boom-workflow", name="Boom", telemetry=False, steps=[Step(name="Boom", executor=exploding_step)]
    )

    events = [event async for event in run_entity(workflow, FakeRunInput())]
    assert_valid_agui_stream(events)

    assert events[-1].type == EventType.RUN_ERROR
    assert "step exploded" in events[-1].message
    assert EventType.RUN_FINISHED not in event_types(events)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_a_cancelled_workflow_does_not_finish_the_run(run_stream):
    events = run_stream([WorkflowCancelledEvent(reason="user pressed stop")])

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message == "user pressed stop"
    assert EventType.RUN_FINISHED not in event_types(events)


def test_a_cancelled_workflow_reports_a_cancellation_code(run_stream):
    events = run_stream([WorkflowCancelledEvent(reason="user pressed stop")])

    assert events[-1].code == WorkflowRunEvent.workflow_cancelled.value


def test_a_cancelled_workflow_without_a_reason_still_ends_the_run_with_an_error(run_stream):
    events = run_stream([WorkflowCancelledEvent()])

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message
    assert EventType.RUN_FINISHED not in event_types(events)


def test_a_cancelled_workflow_closes_open_spans_before_the_error(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="Plan"),
            WorkflowCancelledEvent(reason="cancelled mid step"),
        ]
    )

    types = event_types(events)
    assert types.index(EventType.STEP_FINISHED) < types.index(EventType.RUN_ERROR)
    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message == "cancelled mid step"


def test_a_completion_following_a_cancellation_does_not_report_success(run_stream):
    """cancel_run() makes the engine emit WorkflowCancelled and then WorkflowCompleted."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Plan"),
            WorkflowCancelledEvent(reason="run was cancelled"),
            WorkflowCompletedEvent(content="run was cancelled"),
        ]
    )

    types = event_types(events)
    assert types.index(EventType.STEP_FINISHED) < types.index(EventType.RUN_ERROR)
    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message == "run was cancelled"
    assert EventType.RUN_FINISHED not in types


def test_an_agent_cancellation_is_left_untouched(run_stream):
    """Agent and team cancellation keep their existing raw-event behaviour."""
    events = run_stream([AgentRunCancelledEvent(reason="stopped")])

    assert event_types(events) == [EventType.RAW, EventType.RUN_FINISHED]


def test_a_real_workflow_cancelled_by_a_rejected_step_does_not_finish_the_run():
    workflow = build_cancel_on_reject_workflow()
    paused = workflow.run("go", session_id="cancel-session")
    assert paused.status == RunStatus.paused
    paused.step_requirements[0].reject()

    events = validated(drive_sync_mapper)(workflow.continue_run(paused, stream=True, stream_events=True))

    assert events[-1].type == EventType.RUN_ERROR
    assert "rejected" in events[-1].message
    assert EventType.RUN_FINISHED not in event_types(events)


@pytest.mark.asyncio
async def test_a_real_async_workflow_cancelled_by_a_rejected_step_does_not_finish_the_run():
    workflow = build_cancel_on_reject_workflow()
    paused = await workflow.arun("go", session_id="cancel-session")
    assert paused.status == RunStatus.paused
    paused.step_requirements[0].reject()

    events = await drain_async_mapper(await workflow.acontinue_run(paused, stream=True, stream_events=True))
    assert_valid_agui_stream(events)

    assert events[-1].type == EventType.RUN_ERROR
    assert "rejected" in events[-1].message
    assert EventType.RUN_FINISHED not in event_types(events)


# ---------------------------------------------------------------------------
# Concurrent and repeated steps
# ---------------------------------------------------------------------------
#
# AG-UI names a step and refuses a name it already holds open, so two steps a Parallel
# runs at once cannot both be announced under one name. The second is announced under
# that name plus a counter instead, which is why "Work" and "Work 2" appear below where
# the workflow declares one step called Work. Sequential steps reusing a name are
# untouched: the first has finished before the second starts.


def deltas_of(events):
    return [event.delta for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT]


def assert_spans_balanced(events, expected_names):
    started = [event.step_name for event in events if event.type == EventType.STEP_STARTED]
    finished = [event.step_name for event in events if event.type == EventType.STEP_FINISHED]
    assert started == expected_names
    assert sorted(finished) == sorted(expected_names)


def test_concurrent_steps_do_not_share_one_text_attribution(run_stream):
    """A step that streamed nothing must still emit its output while a sibling step is open."""
    events = run_stream(
        [
            StepStartedEvent(step_name="A", step_id="a", step_index=(0, 0)),
            StepStartedEvent(step_name="B", step_id="b", step_index=(0, 1)),
            RunContentEvent(content="A streams this", step_id="a", step_name="A"),
            StepCompletedEvent(step_name="A", step_id="a", step_index=(0, 0), content="A streams this"),
            StepCompletedEvent(step_name="B", step_id="b", step_index=(0, 1), content="B computed this"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["A streams this", "B computed this"]
    assert_spans_balanced(events, ["A", "B"])


def test_text_naming_no_step_suppresses_no_step_s_output(run_stream):
    """Text that names no step is credited to none, so no step loses its own output.

    Crediting it to a step picked by the stream, whichever that is, silently suppresses
    the output of the step picked wrong. The cost of crediting it to nobody is that the
    step that really produced it repeats it at its completion, which is text the client
    has already seen rather than text it never gets.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="A", step_id="a", step_index=(0, 0)),
            StepStartedEvent(step_name="B", step_id="b", step_index=(0, 1)),
            RunContentEvent(content="A streams this"),
            StepCompletedEvent(step_name="A", step_id="a", step_index=(0, 0), content="A streams this"),
            StepCompletedEvent(step_name="B", step_id="b", step_index=(0, 1), content="B computed this"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["A streams this", "A streams this", "B computed this"]
    assert_spans_balanced(events, ["A", "B"])


def test_text_naming_no_step_does_not_suppress_a_later_step_s_output(run_stream):
    """Unattributed text belongs to the moment it arrived in, not to the rest of the run.

    A step that closes without text of its own answers for nothing, and remembering the
    text past that point hands it to a step that started after it was sent.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="A", step_id="a", step_index=0),
            RunContentEvent(content="A streams this"),
            StepCompletedEvent(step_name="A", step_id="a", step_index=0),
            StepStartedEvent(step_name="B", step_id="b", step_index=1),
            StepCompletedEvent(step_name="B", step_id="b", step_index=1, content="B computed this"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["A streams this", "B computed this"]


def test_unattributed_text_does_not_suppress_the_output_of_a_step_that_closes_first(run_stream):
    """Under a parallel the first step to close is not the step that produced the text.

    Both steps here are open when text arrives naming neither of them. Handing it to
    whichever closes first costs that step its own output and says nothing true about
    the step that actually streamed.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="A", step_id="a", step_index=(0, 0)),
            StepStartedEvent(step_name="B", step_id="b", step_index=(0, 1)),
            RunContentEvent(content="B streams this"),
            StepCompletedEvent(step_name="A", step_id="a", step_index=(0, 0), content="A computed this"),
            StepCompletedEvent(step_name="B", step_id="b", step_index=(0, 1), content="B streams this"),
            WorkflowCompletedEvent(),
        ]
    )

    assert "A computed this" in deltas_of(events)


def test_text_stamped_with_a_step_id_no_span_answers_to_credits_no_step(run_stream):
    """An id matching no open span names no step here, so it may not stand in for one.

    Treating it as unattributed and handing it to the next step to close is the same
    mistake as the one above, made without even the excuse of a missing id.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="A", step_id="a", step_index=(0, 0)),
            StepStartedEvent(step_name="B", step_id="b", step_index=(0, 1)),
            RunContentEvent(content="from a step nobody started", step_id="ghost"),
            StepCompletedEvent(step_name="A", step_id="a", step_index=(0, 0), content="A computed this"),
            StepCompletedEvent(step_name="B", step_id="b", step_index=(0, 1), content="B computed this"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["from a step nobody started", "A computed this", "B computed this"]
    assert_spans_balanced(events, ["A", "B"])


def test_two_concurrent_steps_sharing_a_name_are_tracked_separately(run_stream):
    """The second of two steps open at once under one name is announced under a counted name."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Work", step_id="w1", step_index=(0, 0)),
            StepStartedEvent(step_name="Work", step_id="w2", step_index=(0, 1)),
            RunContentEvent(content="first streamed", step_id="w1", step_name="Work"),
            StepCompletedEvent(step_name="Work", step_id="w1", step_index=(0, 0), content="first streamed"),
            StepCompletedEvent(step_name="Work", step_id="w2", step_index=(0, 1), content="second computed"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["first streamed", "second computed"]
    assert_spans_balanced(events, ["Work", "Work 2"])


def test_a_repeated_name_is_still_disambiguated_without_a_step_id_on_completion(run_stream):
    """The sync engine path omits step_id from its completion events, leaving only step_index."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Work", step_id="w1", step_index=(0, 0)),
            StepStartedEvent(step_name="Work", step_id="w2", step_index=(0, 1)),
            RunContentEvent(content="first streamed", step_id="w1", step_name="Work"),
            StepCompletedEvent(step_name="Work", step_index=(0, 0), content="first streamed"),
            StepCompletedEvent(step_name="Work", step_index=(0, 1), content="second computed"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["first streamed", "second computed"]
    assert_spans_balanced(events, ["Work", "Work 2"])


def test_two_concurrent_steps_sharing_a_name_both_stream_their_own_text(run_stream):
    """Both siblings stream, so neither of them may be treated as the other's output."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Work", step_id="w1", step_index=(0, 0)),
            StepStartedEvent(step_name="Work", step_id="w2", step_index=(0, 1)),
            RunContentEvent(content="from one", step_id="w1", step_name="Work"),
            RunContentEvent(content="from two", step_id="w2", step_name="Work"),
            StepCompletedEvent(step_name="Work", step_id="w1", step_index=(0, 0), content="from one"),
            StepCompletedEvent(step_name="Work", step_id="w2", step_index=(0, 1), content="from two"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["from one", "from two"]
    assert_spans_balanced(events, ["Work", "Work 2"])


def test_concurrent_steps_sharing_a_name_may_complete_out_of_order(run_stream):
    """A Parallel's children finish in whatever order they finish in, not the order they started."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Work", step_id="w1", step_index=(0, 0)),
            StepStartedEvent(step_name="Work", step_id="w2", step_index=(0, 1)),
            StepCompletedEvent(step_name="Work", step_id="w2", step_index=(0, 1), content="second finished first"),
            StepCompletedEvent(step_name="Work", step_id="w1", step_index=(0, 0), content="first finished second"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["second finished first", "first finished second"]
    assert_spans_balanced(events, ["Work", "Work 2"])
    assert span_events(events) == [
        (EventType.STEP_STARTED, "Work"),
        (EventType.STEP_STARTED, "Work 2"),
        (EventType.STEP_FINISHED, "Work 2"),
        (EventType.STEP_FINISHED, "Work"),
    ]


def test_concurrent_steps_close_in_the_order_they_completed(run_stream):
    """Differently named siblings have no reason to wait for each other."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Slow", step_id="slow", step_index=(0, 0)),
            StepStartedEvent(step_name="Fast", step_id="fast", step_index=(0, 1)),
            StepCompletedEvent(step_name="Fast", step_id="fast", step_index=(0, 1), content="fast done"),
            StepCompletedEvent(step_name="Slow", step_id="slow", step_index=(0, 0), content="slow done"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["fast done", "slow done"]
    assert span_events(events) == [
        (EventType.STEP_STARTED, "Slow"),
        (EventType.STEP_STARTED, "Fast"),
        (EventType.STEP_FINISHED, "Fast"),
        (EventType.STEP_FINISHED, "Slow"),
    ]


def test_two_unnamed_concurrent_steps_do_not_share_one_placeholder_span(run_stream):
    """An unnamed step is announced under a placeholder name, which is counted like any other."""
    events = run_stream(
        [
            StepStartedEvent(step_index=(0, 0)),
            StepStartedEvent(step_index=(0, 1)),
            StepCompletedEvent(step_index=(0, 0), content="first"),
            StepCompletedEvent(step_index=(0, 1), content="second"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["first", "second"]
    assert_spans_balanced(events, ["Step", "Step 2"])


def test_a_nested_workflow_inside_a_parallel_keeps_each_branch_to_itself(run_stream):
    """Each branch runs its own sequence of steps, under its own branch step.

    A branch advancing to its next step says nothing about the other branch, whose steps
    are numbered from zero as well and are still running.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="Left", step_id="left", parent_step_id="par", step_index=(0, 0)),
            StepStartedEvent(step_name="Right", step_id="right", parent_step_id="par", step_index=(0, 1)),
            StepStartedEvent(step_name="Fetch", step_id="l1", parent_step_id="left", step_index=0),
            StepStartedEvent(step_name="Fetch", step_id="r1", parent_step_id="right", step_index=0),
            RunContentEvent(content="left fetched", step_id="l1", step_name="Fetch"),
            StepCompletedEvent(step_name="Fetch", step_id="l1", step_index=0, content="left fetched"),
            StepStartedEvent(step_name="Report", step_id="l2", parent_step_id="left", step_index=1),
            RunContentEvent(content="left reported", step_id="l2", step_name="Report"),
            StepCompletedEvent(step_name="Report", step_id="l2", step_index=1, content="left reported"),
            StepCompletedEvent(step_name="Left", step_id="left", step_index=(0, 0), content="left reported"),
            StepCompletedEvent(step_name="Fetch", step_id="r1", step_index=0, content="right fetched"),
            StepCompletedEvent(step_name="Right", step_id="right", step_index=(0, 1), content="right fetched"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["left fetched", "left reported", "right fetched"]
    assert_spans_balanced(events, ["Left", "Right", "Fetch", "Fetch 2", "Report"])


def test_text_from_a_nested_step_also_counts_for_the_step_containing_it(run_stream):
    """An executor event names only its innermost step, so containment comes from the started events."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Outer", step_id="outer"),
            StepStartedEvent(step_name="Inner", step_id="inner", parent_step_id="outer"),
            RunContentEvent(content="nested output", step_id="inner", step_name="Inner"),
            StepCompletedEvent(step_name="Inner", step_id="inner", content="nested output"),
            StepCompletedEvent(step_name="Outer", step_id="outer", content="nested output"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["nested output"]
    assert_spans_balanced(events, ["Outer", "Inner"])


def test_concurrent_steps_left_open_are_all_closed_before_the_run_ends(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="Work", step_id="w1", step_index=(0, 0)),
            StepStartedEvent(step_name="Work", step_id="w2", step_index=(0, 1)),
            WorkflowCompletedEvent(),
        ]
    )

    types = event_types(events)
    assert types.count(EventType.STEP_STARTED) == 2
    assert types.count(EventType.STEP_FINISHED) == 2
    assert types.index(EventType.STEP_FINISHED) < types.index(EventType.RUN_FINISHED)


def test_an_unknown_step_completion_does_not_emit_a_dangling_finish(run_stream):
    events = run_stream(
        [
            StepStartedEvent(step_name="A", step_id="a"),
            StepCompletedEvent(step_name="Ghost", step_id="ghost", content="never started"),
            StepCompletedEvent(step_name="A", step_id="a", content="a done"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["never started", "a done"]
    assert_spans_balanced(events, ["A"])


def test_an_unknown_step_completion_is_logged_and_keeps_its_output(caplog):
    """Nothing else carries a step's output, so a span the mapper missed cannot cost it.

    It is reported too: a completion for a step the mapper never saw start is a gap in
    the mapping, and swallowing it leaves the gap with nothing to find it by.
    """
    with caplog.at_level(logging.WARNING):
        events = validated(drive_sync_mapper)(
            [
                StepStartedEvent(step_name="A", step_id="a"),
                StepCompletedEvent(step_name="Ghost", step_id="ghost", content="never started"),
                StepCompletedEvent(step_name="A", step_id="a", content="a done"),
                WorkflowCompletedEvent(),
            ]
        )

    assert "never started" in deltas_of(events)
    assert "Ghost" in caplog.text


def test_an_unnamed_step_finishes_under_the_name_it_started_with(run_stream):
    """A step with no name falls back to its id, which its completion event may not carry."""
    events = run_stream(
        [
            StepStartedEvent(step_id="s1", step_index=0),
            StepCompletedEvent(step_index=0, content="out"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["out"]
    assert_spans_balanced(events, ["s1"])


def spans_open_at(events, delta):
    """The step names the client had open when a given text delta reached it."""
    active = []
    for event in events:
        if event.type == EventType.STEP_STARTED:
            active.append(event.step_name)
        elif event.type == EventType.STEP_FINISHED:
            active.remove(event.step_name)
        elif event.type == EventType.TEXT_MESSAGE_CONTENT and event.delta == delta:
            return list(active)
    raise AssertionError(f"no delta {delta!r} in {[event.type for event in events]}")


def test_a_sequential_step_reusing_a_name_keeps_that_name(run_stream):
    """Nothing is contended when the first step of a name finished before the second began."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Work", step_id="w1", step_index=0),
            StepCompletedEvent(step_name="Work", step_id="w1", step_index=0, content="first"),
            StepStartedEvent(step_name="Work", step_id="w2", step_index=1),
            StepCompletedEvent(step_name="Work", step_id="w2", step_index=1, content="second"),
            WorkflowCompletedEvent(),
        ]
    )

    assert_spans_balanced(events, ["Work", "Work"])


def test_a_counted_name_skips_one_a_step_is_genuinely_called(run_stream):
    """A workflow may well declare a step called "Work 2", so the counter must step over it."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Work", step_id="w1", step_index=(0, 0)),
            StepStartedEvent(step_name="Work 2", step_id="real", step_index=(0, 1)),
            StepStartedEvent(step_name="Work", step_id="w2", step_index=(0, 2)),
            WorkflowCompletedEvent(),
        ]
    )

    assert_spans_balanced(events, ["Work", "Work 2", "Work 3"])


def test_a_short_output_survives_appearing_inside_a_siblings_text(run_stream):
    """A step's own output is its own, however much of it another step happened to say.

    Short outputs are the common case, and asking whether the client has already seen a
    step's text by looking for that text in another step's makes "OK" indistinguishable
    from part of "LOOKING".
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="Look", step_id="look", step_index=(0, 0)),
            StepStartedEvent(step_name="Check", step_id="check", step_index=(0, 1)),
            RunContentEvent(content="LOOKING", step_id="look", step_name="Look"),
            StepCompletedEvent(step_name="Look", step_id="look", step_index=(0, 0), content="LOOKING"),
            StepCompletedEvent(step_name="Check", step_id="check", step_index=(0, 1), content="OK"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["LOOKING", "OK"]


def test_a_same_named_sibling_emits_its_output_inside_its_own_span(run_stream):
    """Every step's output reaches the client between that step's own start and finish."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Work", step_id="w1", step_index=(0, 0)),
            StepStartedEvent(step_name="Work", step_id="w2", step_index=(0, 1)),
            StepCompletedEvent(step_name="Work", step_id="w2", step_index=(0, 1), content="second finished first"),
            StepCompletedEvent(step_name="Work", step_id="w1", step_index=(0, 0), content="first finished second"),
            WorkflowCompletedEvent(),
        ]
    )

    assert "Work 2" in spans_open_at(events, "second finished first")
    assert "Work" in spans_open_at(events, "first finished second")


def test_a_long_run_does_not_park_its_transcript_on_every_open_span():
    """A container step stays open for the whole run, so anything kept per span grows with it.

    Text the run never attributed to a step says only that some step produced it, which
    is one bit, and keeping the text itself instead makes a step's own output depend on
    what unrelated steps happened to say.
    """
    state = StreamState()
    state.open_step(step_name="Pipeline", step_id="pipe")
    payload = "an unattributed sentence the mapper has no business remembering. "
    for _ in range(50):
        on_run_content(RunContentEvent(content=payload), state)

    retained = "".join(value for span in state.spans for value in vars(span).values() if isinstance(value, str))
    assert payload not in retained


def test_the_span_a_drain_finishes_is_the_span_it_removes():
    """A drain finishes the step that closed, not whichever step compares equal to it.

    Two live spans cannot compare equal today, because the display name a step is
    announced under is unique among the spans still held. This pins the drain to
    identity so that stays an accident of naming rather than the thing holding the
    lifecycle together.
    """
    state = StreamState()
    still_running = StepSpan(step_name="Work", step_id="w", display_name="Work")
    finished = StepSpan(step_name="Work", step_id="w", display_name="Work", closed=True)
    state.spans = [still_running, finished]

    assert state.flush_spans() == [SpanTransition(step_name="Work", started=False)]
    assert [id(span) for span in state.spans] == [id(still_running)]


def test_a_repeated_start_still_reports_the_steps_the_run_moved_past():
    """A start the client already holds announces nothing, and still says where the run is.

    The step it supersedes has no completion event of its own, so a start that returns
    early leaves that step open until the run's terminal event closes it.
    """
    state = StreamState()
    state.open_step(step_name="Second", step_id="s", step_index=1)
    state.open_step(step_name="First", step_id="f", step_index=0)

    assert state.open_step(step_name="Second", step_id="s", step_index=1) == [
        SpanTransition(step_name="First", started=False)
    ]


def test_an_aborted_run_finishes_a_container_after_the_step_inside_it(run_stream):
    """A cancellation ends steps the engine never reported on, and nesting still holds.

    Both steps here are called Work, so the inner one is the contended case, and its span
    must still open before the span containing it closes.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="Work", step_id="outer"),
            StepStartedEvent(step_name="Work", step_id="inner", parent_step_id="outer"),
            WorkflowCancelledEvent(reason="user pressed stop"),
        ]
    )

    assert span_events(events) == [
        (EventType.STEP_STARTED, "Work"),
        (EventType.STEP_STARTED, "Work 2"),
        (EventType.STEP_FINISHED, "Work 2"),
        (EventType.STEP_FINISHED, "Work"),
    ]


def test_a_completion_naming_an_unknown_step_id_closes_nothing(run_stream):
    """A completion names one step by id, so an id nothing matches names no open step."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Work", step_id="w1", step_index=0),
            StepCompletedEvent(step_name="Work", step_id="ghost", step_index=0, content="from nowhere"),
            StepCompletedEvent(step_name="Work", step_id="w1", step_index=0, content="w1 done"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["from nowhere", "w1 done"]
    assert_spans_balanced(events, ["Work"])


def test_a_completion_naming_an_unknown_step_id_leaves_a_running_subtree_alone(run_stream):
    """Closing the wrong step closes everything inside it too, so the mistake cascades."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Outer", step_id="outer", step_index=0),
            StepStartedEvent(step_name="Inner", step_id="inner", parent_step_id="outer"),
            StepCompletedEvent(step_name="Outer", step_id="ghost", step_index=0, content="from nowhere"),
            RunContentEvent(content="inner still running", step_id="inner", step_name="Inner"),
            StepCompletedEvent(step_name="Inner", step_id="inner", content="inner still running"),
            StepCompletedEvent(step_name="Outer", step_id="outer", step_index=0, content="inner still running"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["from nowhere", "inner still running"]
    assert spans_open_at(events, "inner still running") == ["Outer", "Inner"]
    assert span_events(events) == [
        (EventType.STEP_STARTED, "Outer"),
        (EventType.STEP_STARTED, "Inner"),
        (EventType.STEP_FINISHED, "Inner"),
        (EventType.STEP_FINISHED, "Outer"),
    ]


# ---------------------------------------------------------------------------
# Terminal outcome matrix
# ---------------------------------------------------------------------------
#
# One row per outcome the workflow engine can reach, each declaring the terminal AG-UI
# event the client is owed. RunTerminalTracker decides that terminal event from three
# predicates: the terminal event sets, the latch that keeps a run the workflow reported
# unfinished from being reopened, and the step_results scan a completion event goes
# through. Nothing else enumerates the outcome space, so a change to one predicate has
# regressed its neighbours without failing a test. This table is the artefact any future
# terminal-mapping change has to keep green.
#
# Every event shape below was taken from a real engine run, not invented.


def outcome_clean_completion():
    return [
        StepStartedEvent(step_name="Plan"),
        StepCompletedEvent(step_name="Plan", content="a plan"),
        WorkflowCompletedEvent(
            content="a plan",
            step_results=[StepOutput(step_name="Plan", content="a plan", success=True)],
        ),
    ]


def outcome_skip_on_failure():
    """Step(skip_on_failure=True): the failed step is skipped and the run keeps going.

    The engine names neither the skipped step nor its id on the result it leaves behind,
    and never sends its StepCompletedEvent.
    """
    return [
        StepStartedEvent(step_name="Boom", step_index=0),
        StepStartedEvent(step_name="After", step_index=1),
        StepCompletedEvent(step_name="After", step_index=1, content="ran anyway"),
        WorkflowCompletedEvent(
            content="ran anyway",
            step_results=[
                StepOutput(content="Step Boom failed but skipped", success=False, error="step exploded"),
                StepOutput(step_name="After", content="ran anyway", success=True),
            ],
        ),
    ]


def outcome_on_error_skip():
    """HumanReview(on_error="skip"), the default error policy: the run completes."""
    return [
        StepStartedEvent(step_name="Boom", step_index=0),
        StepStartedEvent(step_name="After", step_index=1),
        StepCompletedEvent(step_name="After", step_index=1, content="ran anyway"),
        WorkflowCompletedEvent(
            content="ran anyway",
            step_results=[
                StepOutput(step_name="Boom", success=False, error="step exploded"),
                StepOutput(step_name="After", content="ran anyway", success=True),
            ],
        ),
    ]


def outcome_genuine_failure():
    return [
        StepStartedEvent(step_name="Boom"),
        WorkflowCompletedEvent(
            content="Step skipped due to error: step exploded",
            step_results=[
                StepOutput(
                    step_name="Boom",
                    content="Step skipped due to error: step exploded",
                    success=False,
                    error="step exploded",
                )
            ],
        ),
    ]


def outcome_failure_in_a_nested_result_list():
    """step_results is a recursive union: an element may itself be a list of results."""
    return [
        WorkflowCompletedEvent(
            step_results=[
                [
                    StepOutput(step_name="Ok", content="fine", success=True),
                    StepOutput(step_name="Boom", success=False, error="nested exploded"),
                ]
            ],
        ),
    ]


def outcome_workflow_error():
    return [
        StepStartedEvent(step_name="Plan"),
        WorkflowErrorEvent(error="the step blew up", error_type="ValueError"),
    ]


def outcome_top_level_cancellation():
    return [WorkflowCancelledEvent(run_id="outer-run", reason="user pressed stop")]


def outcome_nested_cancellation_then_outer_success():
    """A nested workflow shares its parent's stream, tagged by run_id and nested_depth.

    Verified against the engine: a workflow run as a step emits its own terminal event
    onto the same stream, at nested_depth 1 and under its own run id. A cancellation
    down there does not cancel the run the client asked for.
    """
    return [
        WorkflowCancelledEvent(run_id="inner-run", nested_depth=1, reason="inner cancelled"),
        WorkflowCompletedEvent(run_id="outer-run", nested_depth=0, content="outer finished anyway"),
    ]


def outcome_workflow_paused():
    return [WorkflowPausedEvent(paused_step_name="Gate", status="paused")]


def outcome_step_paused_for_confirmation():
    """The whole stream a run parked on a confirmation gate produces."""
    return [
        StepPausedEvent(step_name="Gate", step_index=0, requires_confirmation=True),
    ]


def outcome_step_error_under_on_error_pause():
    """HumanReview(on_error="pause"): the stream stops on StepError with no terminal event."""
    return [
        StepStartedEvent(step_name="Boom", step_index=0),
        StepErrorEvent(step_name="Boom", step_index=0, error="step exploded"),
    ]


def outcome_agent_cancellation():
    return [AgentRunCancelledEvent(reason="stopped")]


TERMINAL_OUTCOMES = [
    pytest.param(outcome_clean_completion, EventType.RUN_FINISHED, id="clean_completion"),
    pytest.param(
        outcome_skip_on_failure,
        EventType.RUN_FINISHED,
        id="completion_with_a_skip_on_failure_step",
    ),
    pytest.param(
        outcome_on_error_skip,
        EventType.RUN_FINISHED,
        id="completion_with_on_error_skip",
    ),
    pytest.param(outcome_genuine_failure, EventType.RUN_ERROR, id="completion_whose_failed_step_is_last"),
    pytest.param(
        outcome_failure_in_a_nested_result_list,
        EventType.RUN_ERROR,
        id="completion_whose_failure_sits_in_a_nested_result_list",
    ),
    pytest.param(outcome_workflow_error, EventType.RUN_ERROR, id="workflow_error"),
    pytest.param(outcome_top_level_cancellation, EventType.RUN_ERROR, id="top_level_cancellation"),
    pytest.param(
        outcome_nested_cancellation_then_outer_success,
        EventType.RUN_FINISHED,
        id="nested_cancellation_then_outer_success",
    ),
    pytest.param(
        outcome_workflow_paused,
        EventType.RUN_ERROR,
        id="workflow_paused",
    ),
    pytest.param(
        outcome_step_paused_for_confirmation,
        EventType.RUN_ERROR,
        id="step_paused_for_confirmation",
    ),
    pytest.param(
        outcome_step_error_under_on_error_pause,
        EventType.RUN_ERROR,
        id="step_error_under_on_error_pause",
    ),
    pytest.param(outcome_agent_cancellation, EventType.RUN_FINISHED, id="agent_cancellation_is_unchanged"),
]


@pytest.mark.parametrize("build_chunks, expected_terminal", TERMINAL_OUTCOMES)
def test_terminal_outcome_matrix(run_stream, build_chunks, expected_terminal):
    """Every engine outcome maps to exactly one terminal AG-UI event, and it is the last one.

    The agent cancellation row is a guard: it pins today's agent behaviour so a workflow
    fix cannot change the agent path as a side effect.
    """
    events = run_stream(build_chunks())

    assert events[-1].type == expected_terminal
    opposite = EventType.RUN_FINISHED if expected_terminal is EventType.RUN_ERROR else EventType.RUN_ERROR
    assert opposite not in event_types(events)


def test_a_workflow_error_terminal_carries_its_reason_and_code(run_stream):
    events = run_stream(outcome_workflow_error())

    assert events[-1].message == "the step blew up"
    assert events[-1].code == "ValueError"


def test_a_cancellation_terminal_carries_its_reason_and_code(run_stream):
    events = run_stream(outcome_top_level_cancellation())

    assert events[-1].message == "user pressed stop"
    assert events[-1].code == WorkflowRunEvent.workflow_cancelled.value


# ---------------------------------------------------------------------------
# Pause shapes
# ---------------------------------------------------------------------------
#
# A pause reaches the stream as several events at different levels, and the engine
# declares one pause value it does not yet emit an event class for. All of them park the
# run, and the AG-UI interface offers a workflow no way to resume, so none of them may
# be reported to the client as a finish.


PAUSE_SHAPES = [
    pytest.param(
        lambda: WorkflowPausedEvent(paused_step_name="Gate", status="paused"),
        WorkflowRunEvent.workflow_paused,
        id="workflow_paused",
    ),
    pytest.param(
        lambda: StepPausedEvent(step_name="Gate", step_index=0, requires_confirmation=True),
        WorkflowRunEvent.step_paused,
        id="step_paused",
    ),
    pytest.param(
        lambda: StepExecutorPausedEvent(step_name="Gate", step_index=0, executor_type="agent"),
        WorkflowRunEvent.step_executor_paused,
        id="step_executor_paused",
    ),
    pytest.param(
        lambda: RouterPausedEvent(step_name="Gate", step_index=0, available_choices=["left", "right"]),
        WorkflowRunEvent.router_paused,
        id="router_paused",
    ),
    pytest.param(
        # The engine declares this outcome without a dedicated event class so far
        lambda: StepPausedEvent(event=WorkflowRunEvent.condition_paused.value, step_name="Gate"),
        WorkflowRunEvent.condition_paused,
        id="condition_paused",
    ),
    pytest.param(
        # An output review and a loop iteration review both park the run under this
        # event, and the engine returns straight after it, so it is the last one sent.
        lambda: StepOutputReviewEvent(step_name="Gate", step_index=0, output_review_message="approve?"),
        WorkflowRunEvent.step_output_review,
        id="step_output_review",
    ),
]


@pytest.mark.parametrize("build_chunk, expected_code", PAUSE_SHAPES)
def test_every_pause_shape_ends_the_run_naming_the_pause(run_stream, build_chunk, expected_code):
    events = run_stream([StepStartedEvent(step_name="Gate"), build_chunk()])

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].code == expected_code.value
    assert "Gate" in events[-1].message
    assert EventType.RUN_FINISHED not in event_types(events)


def test_a_pause_without_a_step_name_still_ends_the_run(run_stream):
    events = run_stream([WorkflowPausedEvent(status="paused")])

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message


def test_the_step_pause_and_the_workflow_pause_end_the_run_once(run_stream):
    """A pause is announced by the inner step event and again by the workflow event."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Gate"),
            StepPausedEvent(step_name="Gate", step_index=0, requires_confirmation=True),
            WorkflowPausedEvent(paused_step_name="Gate", status="paused"),
        ]
    )

    assert event_types(events).count(EventType.RUN_ERROR) == 1
    assert events[-1].code == WorkflowRunEvent.workflow_paused.value


def test_a_completion_following_a_pause_does_not_report_success(run_stream):
    events = run_stream(
        [
            WorkflowPausedEvent(paused_step_name="Gate", status="paused"),
            WorkflowCompletedEvent(content="done"),
        ]
    )

    assert events[-1].type == EventType.RUN_ERROR
    assert EventType.RUN_FINISHED not in event_types(events)


def test_an_executor_pause_does_not_offer_tool_calls_the_client_cannot_answer(run_stream):
    """Executor HITL inside a workflow: the agent's own pause is followed by the workflow's.

    The AG-UI route resumes agents and teams from trailing tool messages but never a
    workflow, so tool calls raised here would ask the client for an answer it has
    nowhere to send.

    The tool carries a pause flag, which is what puts it in one of the three partitions
    ``on_run_completed`` builds its cards from. A flagless tool raises no card on any
    path, so the absence below would hold whatever the workflow pause did.
    """
    tool = ToolExecution(tool_call_id="tc-1", tool_name="approve", tool_args={}, requires_confirmation=True)
    events = run_stream(
        [
            AgentRunPausedEvent(tools=[tool], content="waiting"),
            StepExecutorPausedEvent(step_name="Gate", step_index=0, executor_type="agent"),
            WorkflowPausedEvent(paused_step_name="Gate", status="paused"),
        ]
    )

    assert events[-1].type == EventType.RUN_ERROR
    assert EventType.TOOL_CALL_START not in event_types(events)


# ---------------------------------------------------------------------------
# Runs the client did not ask for
# ---------------------------------------------------------------------------
#
# A nested workflow and a step's own agent or team both report their endings onto the
# stream the client is watching. Neither of them ended that stream's run.


def test_a_nested_workflow_error_does_not_bury_the_outer_run(run_stream):
    events = run_stream(
        [
            WorkflowErrorEvent(run_id="inner-run", nested_depth=1, error="inner blew up"),
            WorkflowCompletedEvent(run_id="outer-run", nested_depth=0, content="outer finished anyway"),
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    assert EventType.RUN_ERROR not in event_types(events)


def test_a_nested_workflow_pause_does_not_bury_the_outer_run(run_stream):
    events = run_stream(
        [
            WorkflowPausedEvent(run_id="inner-run", nested_depth=1, paused_step_name="Gate"),
            WorkflowCompletedEvent(run_id="outer-run", nested_depth=0, content="outer finished anyway"),
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    assert EventType.RUN_ERROR not in event_types(events)


def test_a_nested_completion_does_not_overrule_the_outer_cancellation(run_stream):
    """The nested run reports its ending after the run the client asked for ended."""
    events = run_stream(
        [
            WorkflowCancelledEvent(run_id="outer-run", reason="user pressed stop"),
            WorkflowCompletedEvent(run_id="inner-run", nested_depth=1, content="inner finished"),
        ]
    )

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message == "user pressed stop"


def test_a_team_member_failure_is_not_the_team_run_s_own_ending(run_stream):
    """A member run carries the run that started it, and leaves the nesting depth at zero.

    The team went on to answer, so the run the client is watching did not fail, and a
    depth of zero must not be read as the member speaking for the team.
    """
    events = run_stream(
        [
            AgentRunErrorEvent(run_id="member-run", parent_run_id="run-1", content="the member failed"),
            TeamRunContentEvent(run_id="run-1", content="answered without it"),
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    assert EventType.RUN_ERROR not in event_types(events)
    assert deltas_of(events) == ["answered without it"]


def test_a_team_s_own_failure_still_ends_the_run(run_stream):
    """The control for the case above: the team's own error carries no parent run."""
    events = run_stream([TeamRunErrorEvent(run_id="run-1", content="the team failed")])

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message == "the team failed"


def test_an_executor_error_a_step_carried_on_past_does_not_fail_the_run(run_stream):
    """A step's agent errors, the step tolerates it, and the workflow completes."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Ask", step_id="ask"),
            AgentRunErrorEvent(content="model refused", step_id="ask"),
            StepCompletedEvent(step_name="Ask", step_id="ask", content="fell back"),
            WorkflowCompletedEvent(content="fell back"),
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    assert EventType.RUN_ERROR not in event_types(events)


# ---------------------------------------------------------------------------
# An ended run stays ended
# ---------------------------------------------------------------------------
#
# The workflow reports that a run did not finish once, and the stream carries on: the
# engine repeats the ending as a completion event, and a step's own agent or team can
# report an error of its own after it. Neither may talk the mapper back into a success.


UNFINISHED_THEN_AGENT_ERROR = [
    pytest.param(
        lambda: StepErrorEvent(step_name="Boom", step_index=0, error="step exploded"),
        None,
        id="step_error",
    ),
    pytest.param(
        lambda: WorkflowPausedEvent(paused_step_name="Gate", status="paused"),
        WorkflowRunEvent.workflow_paused.value,
        id="workflow_paused",
    ),
    pytest.param(
        lambda: WorkflowCancelledEvent(reason="user pressed stop"),
        WorkflowRunEvent.workflow_cancelled.value,
        id="workflow_cancelled",
    ),
]


@pytest.mark.parametrize("build_unfinished, expected_code", UNFINISHED_THEN_AGENT_ERROR)
def test_an_agent_error_does_not_reopen_a_run_the_workflow_already_ended(run_stream, build_unfinished, expected_code):
    """An agent error belongs to a step's executor, so it cannot clear the workflow's report."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Boom", step_index=0),
            build_unfinished(),
            AgentRunErrorEvent(content="model refused"),
            WorkflowCompletedEvent(content="done"),
        ]
    )

    assert events[-1].type == EventType.RUN_ERROR
    assert EventType.RUN_FINISHED not in event_types(events)
    if expected_code is not None:
        assert events[-1].code == expected_code


# ---------------------------------------------------------------------------
# Tolerated step failures
# ---------------------------------------------------------------------------


def test_a_failure_inside_the_last_grouped_step_is_not_masked_by_its_container(run_stream):
    """A container reporting success over a failed child leaves the failure unreported.

    Every container step in the engine folds its children into its own success flag, so a
    container that reports success while a child failed is not a summary of a tolerance
    its policy allowed. Nothing followed the container either, so the run stopped there.
    """
    events = run_stream(
        [
            WorkflowCompletedEvent(
                content="done",
                step_results=[
                    StepOutput(
                        step_name="Par",
                        content="done",
                        success=True,
                        steps=[StepOutput(step_name="Boom", success=False, error="child exploded")],
                    )
                ],
            )
        ]
    )

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message == "child exploded"


def test_a_container_failure_the_run_continued_past_still_finishes(run_stream):
    """The engine's own shape for a parallel child failure a later step ran on past."""
    events = run_stream(
        [
            WorkflowCompletedEvent(
                content="ran anyway",
                step_results=[
                    StepOutput(
                        step_name="Par",
                        success=False,
                        steps=[
                            StepOutput(step_name="Boom", success=False, error="child exploded"),
                            StepOutput(step_name="Fine", content="fine", success=True),
                        ],
                    ),
                    StepOutput(step_name="After", content="ran anyway", success=True),
                ],
            )
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    assert EventType.RUN_ERROR not in event_types(events)


def test_the_failure_that_ended_the_run_is_the_one_reported(run_stream):
    """A failure the run carried on past is not the failure the client is owed."""
    events = run_stream(
        [
            WorkflowCompletedEvent(
                step_results=[
                    StepOutput(step_name="Skipped", success=False, error="a failure the run survived"),
                    StepOutput(step_name="After", content="ran anyway", success=True),
                    StepOutput(step_name="Boom", success=False, error="the failure that ended the run"),
                ],
            )
        ]
    )

    assert events[-1].type == EventType.RUN_ERROR
    assert events[-1].message == "the failure that ended the run"


def test_a_run_that_continued_past_a_skipped_step_keeps_its_final_state_snapshot():
    """Reporting a completed run as failed also costs the client the state it ended with."""
    events = list(
        stream_agno_response_as_agui_events(
            iter(outcome_skip_on_failure()),
            thread_id="thread-1",
            run_id="run-1",
            run_state={"count": 1},
        )
    )
    assert_valid_agui_stream(events)

    assert events[-1].type == EventType.RUN_FINISHED
    assert EventType.STATE_SNAPSHOT in event_types(events)


def test_a_failure_in_a_nested_result_list_names_the_inner_error(run_stream):
    events = run_stream(outcome_failure_in_a_nested_result_list())

    assert events[-1].message == "nested exploded"


def test_a_run_that_continued_past_a_grouped_failure_still_finishes(run_stream):
    """Descending into a grouped element must not turn a survived failure into a fatal one.

    A step that opts out of aborting leaves a failed result behind and the run carries on,
    so a result following the failure means the run really did complete.
    """
    events = run_stream(
        [
            WorkflowCompletedEvent(
                step_results=[
                    [
                        StepOutput(step_name="Ok", content="fine", success=True),
                        StepOutput(step_name="Boom", success=False, error="nested exploded"),
                    ],
                    StepOutput(step_name="After", content="ran anyway", success=True),
                ],
            ),
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    assert EventType.RUN_ERROR not in event_types(events)


# ---------------------------------------------------------------------------
# Engine payload shape corpus
# ---------------------------------------------------------------------------
#
# The mapper consumes engine payloads whose declared types are Any or recursive unions,
# and each consumption site re-derives its own traversal with getattr defaults and
# isinstance chains. A shape the site did not anticipate does not raise there: it
# returns the default and the run continues with the wrong answer. These rows feed both
# traversal points every shape the engine declares, and assert that each one has a
# defined outcome and that none of them escapes the mapper as an exception.


class StructuredStepOutput(BaseModel):
    title: str


def yielded_step_names(results):
    return [getattr(result, "step_name", None) for result in _iter_step_results(results)]


STEP_RESULT_SHAPES = [
    pytest.param(None, [], id="none_instead_of_a_list"),
    pytest.param([], [], id="empty_list"),
    pytest.param(
        [StepOutput(step_name="A"), StepOutput(step_name="B")],
        ["A", "B"],
        id="flat_list",
    ),
    pytest.param(
        [StepOutput(step_name="A"), None, StepOutput(step_name="B")],
        ["A", "B"],
        id="list_with_a_none_entry",
    ),
    pytest.param(
        [StepOutput(step_name="Par", steps=[StepOutput(step_name="Ok"), StepOutput(step_name="Boom")])],
        ["Ok", "Boom", "Par"],
        id="result_carrying_children_under_steps",
    ),
    pytest.param(
        [[StepOutput(step_name="Ok"), StepOutput(step_name="Boom")]],
        ["Ok", "Boom"],
        id="bare_nested_list_element",
    ),
    pytest.param(
        [StepOutput(step_name="A"), [StepOutput(step_name="Ok"), StepOutput(step_name="Boom")]],
        ["A", "Ok", "Boom"],
        id="mixed_list_of_results_and_lists",
    ),
    pytest.param(
        [[StepOutput(step_name="Par", steps=[StepOutput(step_name="Ok")])]],
        ["Ok", "Par"],
        id="bare_list_element_whose_result_carries_children",
    ),
    pytest.param(
        [[None, StepOutput(step_name="Ok")]],
        ["Ok"],
        id="bare_list_element_with_a_none_entry",
    ),
    pytest.param([[]], [], id="empty_bare_list_element"),
]


@pytest.mark.parametrize("results, expected_names", STEP_RESULT_SHAPES)
def test_every_declared_step_result_shape_is_walked(results, expected_names):
    """step_results is declared List[Union[StepOutput, List[StepOutput]]] and the run
    output flattens both forms, so the walker has to reach a result under either one."""
    assert yielded_step_names(results) == expected_names


STEP_CONTENT_SHAPES = [
    pytest.param("plain text", "plain text", id="str"),
    pytest.param({"role": "user", "content": "from a dict"}, "from a dict", id="dict_carrying_content"),
    pytest.param({"summary": "no content key"}, "no content key", id="dict_without_a_content_key"),
    pytest.param(StructuredStepOutput(title="structured"), "structured", id="basemodel"),
    pytest.param(Message(role="user", content="from a message"), "from a message", id="message"),
    pytest.param(
        [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}],
        "first\nsecond",
        id="list_of_typed_dicts",
    ),
    pytest.param(
        [{"summary": "first"}, {"summary": "second"}],
        "first",
        id="list_of_plain_dicts",
    ),
    pytest.param(
        ["first", "second"],
        "first",
        id="list_of_strings",
    ),
    pytest.param(
        [1, 2, 3],
        "1",
        id="list_of_scalars",
    ),
    pytest.param(42, "42", id="scalar"),
]


@pytest.mark.parametrize("content, expected_text", STEP_CONTENT_SHAPES)
def test_every_step_content_shape_reaches_the_client(run_stream, content, expected_text):
    """StepCompletedEvent.content is Optional[Any] and a step may return any of these."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Step", step_id="s1"),
            StepCompletedEvent(step_name="Step", step_id="s1", content=content),
            WorkflowCompletedEvent(),
        ]
    )

    deltas = deltas_of(events)
    assert len(deltas) == 1
    assert expected_text in deltas[0]


TRANSCRIPT_CONTENTS = [
    pytest.param(
        [Message(role="user", content="what is the capital?"), Message(role="assistant", content="Paris")],
        id="messages",
    ),
    pytest.param(
        [{"role": "user", "content": "what is the capital?"}, {"role": "assistant", "content": "Paris"}],
        id="message_records",
    ),
    pytest.param(
        [
            Message(role="user", content="what is the capital?"),
            Message(role="tool", content='{"capital": "Paris", "population": 2102650}'),
            Message(role="assistant", content="Paris"),
        ],
        id="messages_including_a_tool_result",
    ),
    pytest.param(
        [
            {"role": "user", "content": "what is the capital?"},
            {"role": "tool", "content": '{"capital": "Paris", "population": 2102650}'},
            {"role": "assistant", "content": "Paris"},
        ],
        id="message_records_including_a_tool_result",
    ),
]


@pytest.mark.parametrize("content", TRANSCRIPT_CONTENTS)
def test_a_step_returning_a_transcript_sends_what_it_answered(run_stream, content):
    """A step whose output is a conversation owes the client its reply, not the prompt.

    The interface's reading of message content returns the user turns out of a list of
    messages, so reusing it here sends the caller's own question back as the step's
    answer and drops the answer. A tool turn is the same fault from the other side: the
    raw payload a tool handed the step is not the step's answer either, and sending it
    puts a JSON blob in the assistant text. Both are wrong text on the wire, not missing
    text.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="Ask", step_id="ask"),
            StepCompletedEvent(step_name="Ask", step_id="ask", content=content),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["Paris"]


PLAIN_LIST_CONTENTS = [
    pytest.param(["first", "second"], ["first", "second"], id="strings"),
    pytest.param([1, 2, 3], ["1", "2", "3"], id="scalars"),
    pytest.param([{"summary": "first"}, {"summary": "second"}], ["first", "second"], id="dicts"),
]


@pytest.mark.parametrize("content, expected_parts", PLAIN_LIST_CONTENTS)
def test_a_plain_list_sends_every_element_not_only_the_first(run_stream, content, expected_parts):
    """Dropping the tail of a list would lose output as silently as dropping all of it."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Step", step_id="s1"),
            StepCompletedEvent(step_name="Step", step_id="s1", content=content),
            WorkflowCompletedEvent(),
        ]
    )

    deltas = deltas_of(events)
    assert len(deltas) == 1
    for part in expected_parts:
        assert part in deltas[0]


RECORDS_THE_JSON_SERIALIZER_REFUSES = [
    pytest.param({"kept": "the readable part", "at": datetime(2026, 1, 2, 3, 4, 5)}, id="datetime_value"),
    pytest.param({"kept": "the readable part", "tags": {"a", "b"}}, id="set_value"),
    pytest.param({"kept": "the readable part", "inner": StructuredStepOutput(title="nested")}, id="model_value"),
    pytest.param({"kept": "the readable part", "seen": [datetime(2026, 1, 2)]}, id="value_nested_in_a_list"),
]


@pytest.mark.parametrize("content", RECORDS_THE_JSON_SERIALIZER_REFUSES)
def test_a_record_the_json_serializer_refuses_does_not_end_the_run(run_stream, content):
    """A step returns whatever its executor returned, and json.dumps reads few of those.

    The record still has to reach the reader, and the run still has to reach its end.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="Step", step_id="s1"),
            StepCompletedEvent(step_name="Step", step_id="s1", content=content),
            WorkflowCompletedEvent(),
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    deltas = deltas_of(events)
    assert len(deltas) == 1
    assert "the readable part" in deltas[0]


class Opaque:
    """A value pydantic has no serializer for, whose own text still says what it holds."""

    def __repr__(self) -> str:
        return "the readable part"


class ModelPydanticCannotSerialize(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    title: str
    payload: Opaque


def test_a_model_pydantic_cannot_serialize_does_not_end_the_run(run_stream):
    """A step may return a model holding a value pydantic has no serializer for.

    ``model_dump_json`` raises on it, and an exception leaving the mapper is caught by
    the route, which ends the run with an error in place of the step's output and closes
    none of the spans the client is holding open. The model still has to reach the
    reader, and the run still has to reach its end.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="Step", step_id="s1"),
            StepCompletedEvent(
                step_name="Step",
                step_id="s1",
                content=ModelPydanticCannotSerialize(title="kept", payload=Opaque()),
            ),
            WorkflowCompletedEvent(),
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    deltas = deltas_of(events)
    assert len(deltas) == 1
    assert "kept" in deltas[0]
    assert "the readable part" in deltas[0]


RECORDS_CARRYING_A_CONTENT_KEY = [
    pytest.param(
        {"content": "the summary", "detail": "the sibling the reader also needs"},
        ["the summary", "the sibling the reader also needs"],
        id="content_beside_a_sibling",
    ),
    pytest.param(
        {"content": "", "result": "everything the step produced"},
        ["everything the step produced"],
        id="empty_content_beside_a_sibling",
    ),
    pytest.param(
        {"content": None, "error": "the step said why it failed"},
        ["the step said why it failed"],
        id="null_content_beside_a_sibling",
    ),
]


@pytest.mark.parametrize("content, expected_parts", RECORDS_CARRYING_A_CONTENT_KEY)
def test_a_record_is_not_reduced_to_its_content_key(run_stream, content, expected_parts):
    """A key named content is one key of a record, not a licence to drop the others."""
    events = run_stream(
        [
            StepStartedEvent(step_name="Step", step_id="s1"),
            StepCompletedEvent(step_name="Step", step_id="s1", content=content),
            WorkflowCompletedEvent(),
        ]
    )

    deltas = deltas_of(events)
    assert len(deltas) == 1
    for part in expected_parts:
        assert part in deltas[0]


EMPTY_STEP_CONTENT_SHAPES = [
    pytest.param(None, id="none"),
    pytest.param("", id="empty_str"),
    pytest.param([], id="empty_list"),
    pytest.param(
        {},
        id="empty_dict",
    ),
    pytest.param({"content": {}}, id="dict_whose_content_is_empty"),
    pytest.param({"content": []}, id="dict_whose_content_is_an_empty_list"),
    pytest.param([None, "", {}], id="list_of_empty_entries"),
    pytest.param(Message(role="user"), id="message_with_no_content"),
]


@pytest.mark.parametrize("content", EMPTY_STEP_CONTENT_SHAPES)
def test_a_step_with_no_content_opens_no_message(run_stream, content):
    events = run_stream(
        [
            StepStartedEvent(step_name="Step", step_id="s1"),
            StepCompletedEvent(step_name="Step", step_id="s1", content=content),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == []
    assert EventType.TEXT_MESSAGE_START not in event_types(events)


# ---------------------------------------------------------------------------
# Span lifecycle and text framing
# ---------------------------------------------------------------------------
#
# The stream-wide rules live in _agui_stream_rules and run on every test above through
# the run_stream fixture. The cases below are lifecycle defects the client's own
# verifier does not reject but a reader of the transcript would: identical text sent
# twice, output that never arrives at all, and a span that outlives the step it
# belongs to.


def span_events(events):
    return [(event.type, event.step_name) for event in events if event.type in _SPAN_TYPES]


_SPAN_TYPES = (EventType.STEP_STARTED, EventType.STEP_FINISHED)


def test_a_function_step_output_is_not_re_emitted_by_the_step_containing_it(run_stream):
    """A function step streams nothing, so its output leaves through the completion path.

    That path emits the text without crediting the step, and the enclosing step then
    believes it still owes the client its own output.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="Outer", step_id="outer"),
            StepStartedEvent(step_name="Inner", step_id="inner", parent_step_id="outer"),
            StepCompletedEvent(step_name="Inner", step_id="inner", content="function output"),
            StepCompletedEvent(step_name="Outer", step_id="outer", content="function output"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["function output"]


def test_a_step_that_produced_nothing_does_not_claim_the_output_of_the_step_around_it(run_stream):
    """A nested workflow's steps are children of the outer step, so what they claim it loses.

    An inner step whose completion carries no content has no output to claim, and
    claiming one anyway tells the outer step its own output has already been sent. The
    outer step then emits nothing and the whole nested workflow's answer is dropped.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="Outer", step_id="outer"),
            StepStartedEvent(step_name="Inner", step_id="inner", parent_step_id="outer"),
            StepCompletedEvent(step_name="Inner", step_id="inner", content=None),
            StepCompletedEvent(step_name="Outer", step_id="outer", content="what the nested workflow answered"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["what the nested workflow answered"]


def test_a_completion_matching_no_span_does_not_repeat_text_its_step_already_streamed(run_stream):
    """A span is dropped once its transitions are emitted, and the text it sent is not.

    Here the sequence moves on to a later step, which closes and drains the span of the
    step before it. That step's completion then matches nothing, and treating an
    unmatched completion as unsent output sends the client its own step's text twice.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="One", step_id="one", step_index=0),
            RunContentEvent(content="what One streamed", step_id="one"),
            StepStartedEvent(step_name="Two", step_id="two", step_index=1),
            StepCompletedEvent(step_name="One", step_id="one", step_index=0, content="what One streamed"),
            StepCompletedEvent(step_name="Two", step_id="two", step_index=1, content="what Two computed"),
            WorkflowCompletedEvent(),
        ]
    )

    assert deltas_of(events) == ["what One streamed", "what Two computed"]


def test_a_step_that_ends_first_takes_the_step_still_open_inside_it_with_it(run_stream):
    """A step ending ends everything it contains, whether or not the engine says so.

    Without that, the inner step's STEP_FINISHED waits for the run's terminal event and
    arrives after its own container's and after every step that ran later, which tells
    the client the inner step outlived the step it was running inside.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="Outer", step_id="outer"),
            StepStartedEvent(step_name="Inner", step_id="inner", parent_step_id="outer"),
            StepCompletedEvent(step_name="Outer", step_id="outer", content="outer done"),
            StepStartedEvent(step_name="Next", step_id="next"),
            StepCompletedEvent(step_name="Next", step_id="next", content="next done"),
            WorkflowCompletedEvent(),
        ]
    )

    assert span_events(events) == [
        (EventType.STEP_STARTED, "Outer"),
        (EventType.STEP_STARTED, "Inner"),
        (EventType.STEP_FINISHED, "Inner"),
        (EventType.STEP_FINISHED, "Outer"),
        (EventType.STEP_STARTED, "Next"),
        (EventType.STEP_FINISHED, "Next"),
    ]


def test_a_skipped_step_closes_its_span_before_the_next_step_finishes(run_stream):
    """Step(skip_on_failure=True) sends no StepCompletedEvent for the step it skipped.

    The terminal event closes the span instead, which puts the skipped step's
    STEP_FINISHED after the STEP_FINISHED of every step that ran after it. The existing
    balance helper sorts the finished names, so nesting order is asserted here directly.
    """
    events = run_stream(outcome_skip_on_failure())

    assert span_events(events) == [
        (EventType.STEP_STARTED, "Boom"),
        (EventType.STEP_FINISHED, "Boom"),
        (EventType.STEP_STARTED, "After"),
        (EventType.STEP_FINISHED, "After"),
    ]
