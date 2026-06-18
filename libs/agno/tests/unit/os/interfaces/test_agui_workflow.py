"""Workflow -> AG-UI event translation.

Workflows stream their inner agent/team content through the shared handlers;
every structural WorkflowRunEvent surfaces as a CustomEvent; the terminals
(completed / error) resolve at completion, and cancellation mirrors the
agent/team path (a marker + clean finish, never an error).

Tests feed REAL agno event classes through the in-process
`async_stream_agno_response_as_agui_events` entrypoint (the harness already used
in this file) and assert the EXACT ordered AG-UI events. The structural-event
coverage is driven off the real `STRUCTURAL_EVENT_VALUES` / event registry so a
new WorkflowRunEvent auto-joins and coverage cannot silently drift.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import CustomEvent, EventType, RunStartedEvent

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.os.interfaces.agui.agui import AGUI
from agno.os.interfaces.agui.handlers import HANDLERS, on_custom_event, on_workflow_cancelled
from agno.os.interfaces.agui.router import run_entity
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events
from agno.os.interfaces.agui.workflow_handlers import STRUCTURAL_EVENT_VALUES, _final_leaf_streamed
from agno.reasoning.step import ReasoningStep
from agno.run.agent import (
    ReasoningCompletedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunContentEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.workflow import (
    WORKFLOW_RUN_EVENT_TYPE_REGISTRY,
    RouterExecutionStartedEvent,
    StepCompletedEvent,
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    WorkflowPausedEvent,
    WorkflowRunEvent,
)
from agno.workflow.types import StepOutput, StepType

ET = EventType


def _stream(*chunks):
    """Adapt a list of real event instances into the async stream the entrypoint consumes."""

    async def gen():
        for chunk in chunks:
            yield chunk

    return gen()


async def _collect(stream):
    return [event async for event in async_stream_agno_response_as_agui_events(stream, "t1", "r1")]


def _types(events):
    return [e.type for e in events]


def _deltas(events):
    return [e.delta for e in events if e.type == ET.TEXT_MESSAGE_CONTENT]


def _expected_custom_value(instance):
    # Mirror on_custom_event's value extraction: to_dict(), falling back to .content.
    try:
        return instance.to_dict()
    except Exception:
        return getattr(instance, "content", None)


# ====== AGUI construction ======


def test_agui_accepts_workflow():
    workflow = MagicMock()
    assert AGUI(workflow=workflow).workflow is workflow


def test_agui_requires_an_entity():
    with pytest.raises(ValueError):
        AGUI()


def test_agui_rejects_multiple_entities():
    with pytest.raises(ValueError):
        AGUI(agent=MagicMock(), workflow=MagicMock())


# ====== run_entity passthrough ======


class _CaptureKwargsWorkflow:
    def __init__(self):
        self.captured_kwargs: dict = {}

    async def arun(self, **kwargs):
        self.captured_kwargs = kwargs
        return
        yield


class _FakeRunInput:
    def __init__(self):
        self.messages = [MagicMock(role="user", content="hi")]
        self.thread_id = "t1"
        self.run_id = "r1"
        self.forwarded_props = None
        self.state = None
        self.context = []  # real RunAgentInput field; run_entity reads it via extract_context


@pytest.mark.asyncio
async def test_run_entity_passes_streaming_kwargs_to_workflow():
    workflow = _CaptureKwargsWorkflow()
    async for _ in run_entity(workflow, _FakeRunInput()):
        pass
    assert workflow.captured_kwargs.get("stream") is True
    assert workflow.captured_kwargs.get("stream_events") is True


# ====== Completion gate: the two failure modes are DROP and DUPLICATE ======


@pytest.mark.asyncio
async def test_streamed_final_answer_is_not_re_emitted():
    # Inner content streamed; completion content equals it -> no duplicate.
    events = await _collect(
        _stream(
            RunContentEvent(content="the answer"),
            WorkflowCompletedEvent(
                content="the answer",
                step_results=[StepOutput(content="the answer", executor_type="agent", step_type=StepType.STEP)],
                workflow_name="wf",
            ),
        )
    )
    assert _types(events) == [ET.TEXT_MESSAGE_START, ET.TEXT_MESSAGE_CONTENT, ET.TEXT_MESSAGE_END, ET.RUN_FINISHED]
    assert _deltas(events).count("the answer") == 1


@pytest.mark.asyncio
async def test_non_streamed_final_answer_is_emitted_once():
    # Nothing streamed (e.g. a function step); the final answer lives only in
    # WorkflowCompletedEvent.content and must be emitted exactly once.
    events = await _collect(_stream(WorkflowCompletedEvent(content="final answer", workflow_name="wf")))
    assert _types(events) == [ET.TEXT_MESSAGE_START, ET.TEXT_MESSAGE_CONTENT, ET.TEXT_MESSAGE_END, ET.RUN_FINISHED]
    assert _deltas(events) == ["final answer"]


@pytest.mark.asyncio
async def test_non_streamed_final_after_a_streamed_step_is_not_dropped():
    # An earlier step streamed; the final answer is non-streamed and different.
    # It must NOT be dropped just because something streamed earlier.
    events = await _collect(
        _stream(
            RunContentEvent(content="research notes"),
            WorkflowCompletedEvent(content="FINAL ANSWER", workflow_name="wf"),
        )
    )
    assert _types(events) == [
        ET.TEXT_MESSAGE_START,
        ET.TEXT_MESSAGE_CONTENT,
        ET.TEXT_MESSAGE_END,
        ET.TEXT_MESSAGE_START,
        ET.TEXT_MESSAGE_CONTENT,
        ET.TEXT_MESSAGE_END,
        ET.RUN_FINISHED,
    ]
    deltas = _deltas(events)
    assert "research notes" in deltas
    assert deltas.count("FINAL ANSWER") == 1


@pytest.mark.asyncio
async def test_multi_step_streamed_into_one_message_is_not_duplicated():
    # Two steps stream into one open message (a structural CustomEvent between
    # them does not close it); completion content equals the tail -> the endswith
    # gate skips the re-emit. This is the case a naive '==' check duplicated.
    events = await _collect(
        _stream(
            RunContentEvent(content="step one. "),
            StepCompletedEvent(step_name="s1"),
            RunContentEvent(content="step two final."),
            WorkflowCompletedEvent(
                content="step two final.",
                step_results=[
                    StepOutput(content="step one. ", executor_type="agent", step_type=StepType.STEP),
                    StepOutput(content="step two final.", executor_type="agent", step_type=StepType.STEP),
                ],
                workflow_name="wf",
            ),
        )
    )
    assert _types(events) == [
        ET.TEXT_MESSAGE_START,
        ET.TEXT_MESSAGE_CONTENT,
        ET.CUSTOM,
        ET.TEXT_MESSAGE_CONTENT,
        ET.TEXT_MESSAGE_END,
        ET.RUN_FINISHED,
    ]
    assert _deltas(events).count("step two final.") == 1


# ====== Terminals ======


@pytest.mark.asyncio
async def test_workflow_error_is_terminal_run_error_with_no_finish():
    # Gate CONTRACT (defensive): a terminal workflow_error -> RUN_ERROR, no
    # RUN_FINISHED. In the real async-streaming engine this branch is NOT hit:
    # generic errors raise (run_entity emits RUN_ERROR, see next test) and
    # validation errors get overwritten by a trailing WorkflowCompletedEvent. Kept
    # because it is the correct, cheap translation if a terminal error arrives.
    events = await _collect(_stream(WorkflowErrorEvent(error="boom", workflow_name="wf")))
    assert _types(events) == [ET.RUN_ERROR]
    assert events[0].message == "boom"


@pytest.mark.asyncio
async def test_raising_workflow_stream_surfaces_single_run_error_via_run_entity():
    # Real production error path (workflow.py:2903): the engine yields a
    # WorkflowErrorEvent then RAISES; the raise preempts the completion gate, so
    # run_entity's except (router.py:74) emits exactly one RUN_ERROR. (A raising
    # function STEP does NOT reach here -- step errors are skipped and rendered as
    # "Step skipped due to error: ..."; RUN_ERROR needs an escape from the stream.)
    class _RaisingWorkflow:
        async def arun(self, **kwargs):
            yield WorkflowErrorEvent(error="engine exploded", workflow_name="wf")
            raise RuntimeError("engine exploded")

    events = [e async for e in run_entity(_RaisingWorkflow(), _FakeRunInput())]
    types = [e.type for e in events]
    assert types.count(ET.RUN_ERROR) == 1
    assert types[-1] == ET.RUN_ERROR
    assert "engine exploded" in next(e for e in events if e.type == ET.RUN_ERROR).message


@pytest.mark.asyncio
async def test_workflow_cancelled_is_marker_plus_clean_finish_not_error():
    # Cancel mirrors the agent/team path: a structural CustomEvent marker AND a
    # clean RUN_FINISHED, and NEVER a RUN_ERROR.
    events = await _collect(_stream(WorkflowCancelledEvent(reason="user stop", workflow_name="wf")))
    assert _types(events) == [ET.CUSTOM, ET.RUN_FINISHED]
    assert isinstance(events[0], CustomEvent)
    assert events[0].name == "WorkflowCancelledEvent"
    assert not any(e.type == ET.RUN_ERROR for e in events)


# ====== Structural events -> CustomEvent (single source of truth: the enum) ======


def test_structural_split_and_handler_coverage():
    # Coverage cannot silently drift: STRUCTURAL is exactly the enum minus the
    # two terminals, and EVERY structural value routes to a CustomEvent-emitting
    # handler. workflow_cancelled uses the dedicated on_workflow_cancelled (sets the
    # cancel flag, then delegates to on_custom_event); all others go straight to
    # on_custom_event. Driven off the enum so a new event auto-joins.
    terminals = {WorkflowRunEvent.workflow_completed.value, WorkflowRunEvent.workflow_error.value}
    assert STRUCTURAL_EVENT_VALUES == {e.value for e in WorkflowRunEvent} - terminals
    cancelled = WorkflowRunEvent.workflow_cancelled.value
    assert all(
        HANDLERS.get(value) is (on_workflow_cancelled if value == cancelled else on_custom_event)
        for value in STRUCTURAL_EVENT_VALUES
    )


def test_only_condition_paused_lacks_an_event_class():
    # Guard the one documented gap so it cannot widen silently: agno defines
    # WorkflowRunEvent.condition_paused but ships no event class for it (absent
    # from the registry and the Union, so it is never emitted). The handler still
    # covers it defensively (asserted above). If another value loses its class —
    # or condition_paused gains one — this fails and we revisit.
    missing = STRUCTURAL_EVENT_VALUES - set(WORKFLOW_RUN_EVENT_TYPE_REGISTRY)
    assert missing == {WorkflowRunEvent.condition_paused.value}


# The 28 structural values that ship an event class (all except condition_paused),
# tested end-to-end with real instances below.
_STRUCTURAL_WITH_CLASS = sorted(STRUCTURAL_EVENT_VALUES & set(WORKFLOW_RUN_EVENT_TYPE_REGISTRY))


@pytest.mark.parametrize("event_value", _STRUCTURAL_WITH_CLASS)
@pytest.mark.asyncio
async def test_every_structural_event_becomes_a_custom_event(event_value):
    # Driven off the real enum/registry so any future WorkflowRunEvent auto-joins.
    cls = WORKFLOW_RUN_EVENT_TYPE_REGISTRY[event_value]
    instance = cls()
    events = await _collect(_stream(instance, WorkflowCompletedEvent(content=None, workflow_name="wf")))
    customs = [e for e in events if isinstance(e, CustomEvent)]
    assert len(customs) == 1
    assert customs[0].name == cls.__name__
    assert customs[0].value == _expected_custom_value(instance)


@pytest.mark.asyncio
async def test_structural_custom_event_carries_real_to_dict_payload():
    # Real fields, not just "a CustomEvent fired": the router's selected_steps
    # survive into the CustomEvent payload via to_dict().
    router_event = RouterExecutionStartedEvent(step_name="route", selected_steps=["chat"])
    events = await _collect(_stream(router_event, WorkflowCompletedEvent(content=None, workflow_name="wf")))
    custom = next(e for e in events if isinstance(e, CustomEvent))
    assert custom.name == "RouterExecutionStartedEvent"
    assert custom.value["step_name"] == "route"
    assert custom.value["selected_steps"] == ["chat"]


# ====== Inner agent/team events reuse the shared handlers (no workflow dup) ======


@pytest.mark.asyncio
async def test_inner_tool_call_streams_through_shared_handlers():
    tool = MagicMock()
    tool.tool_call_id = "call_1"
    tool.tool_name = "search"
    tool.tool_args = {"q": "agno"}
    tool.result = "found"
    events = await _collect(
        _stream(
            ToolCallStartedEvent(tool=tool),
            ToolCallCompletedEvent(tool=tool),
            WorkflowCompletedEvent(content=None, workflow_name="wf"),
        )
    )
    assert _types(events) == [
        ET.TEXT_MESSAGE_START,
        ET.TEXT_MESSAGE_END,
        ET.TOOL_CALL_START,
        ET.TOOL_CALL_ARGS,
        ET.TOOL_CALL_END,
        ET.TOOL_CALL_RESULT,
        ET.RUN_FINISHED,
    ]
    start = next(e for e in events if e.type == ET.TOOL_CALL_START)
    assert start.tool_call_id == "call_1"
    assert start.tool_call_name == "search"
    args = next(e for e in events if e.type == ET.TOOL_CALL_ARGS)
    assert args.delta == json.dumps({"q": "agno"})


@pytest.mark.asyncio
async def test_inner_reasoning_streams_through_shared_handlers():
    events = await _collect(
        _stream(
            ReasoningStartedEvent(),
            ReasoningStepEvent(content=ReasoningStep(title="Plan", reasoning="thinking")),
            ReasoningCompletedEvent(),
            WorkflowCompletedEvent(content=None, workflow_name="wf"),
        )
    )
    assert _types(events) == [
        ET.REASONING_START,
        ET.REASONING_MESSAGE_START,
        ET.REASONING_MESSAGE_CONTENT,
        ET.REASONING_MESSAGE_END,
        ET.REASONING_END,
        ET.RUN_FINISHED,
    ]
    content = next(e for e in events if e.type == ET.REASONING_MESSAGE_CONTENT)
    assert "Plan" in content.delta


@pytest.mark.asyncio
async def test_inner_team_content_streams_through_shared_handlers():
    events = await _collect(
        _stream(
            TeamRunContentEvent(content="team answer"),
            WorkflowCompletedEvent(
                content="team answer",
                step_results=[StepOutput(content="team answer", executor_type="team", step_type=StepType.STEP)],
                workflow_name="wf",
            ),
        )
    )
    assert _types(events) == [ET.TEXT_MESSAGE_START, ET.TEXT_MESSAGE_CONTENT, ET.TEXT_MESSAGE_END, ET.RUN_FINISHED]
    assert _deltas(events) == ["team answer"]


# ====== Pause (HITL): degrade gracefully; resume is OUT OF SCOPE / NOT tested ======


@pytest.mark.asyncio
async def test_workflow_paused_degrades_gracefully():
    # A workflow pause surfaces as a structural CustomEvent and the run still
    # finalizes cleanly (no crash, no error). Resume is OUT OF SCOPE and is NOT
    # tested here.
    events = await _collect(_stream(WorkflowPausedEvent(workflow_name="wf")))
    assert _types(events) == [ET.CUSTOM, ET.RUN_FINISHED]
    assert events[0].name == "WorkflowPausedEvent"
    assert not any(e.type == ET.RUN_ERROR for e in events)


# ====== Client disconnect stops the workflow stream ======


@pytest.mark.asyncio
async def test_workflow_stream_stops_on_client_disconnect():
    from fastapi import APIRouter

    from agno.os.interfaces.agui import router as agui_router

    async def fake_run_entity(entity, run_input):
        for _ in range(5):
            yield RunStartedEvent(type=ET.RUN_STARTED, thread_id="t1", run_id="r1")

    request = MagicMock()
    # Connected for the first two events, then disconnected -> break before #3.
    request.is_disconnected = AsyncMock(side_effect=[False, False, True])

    r = APIRouter()
    with patch.object(agui_router, "run_entity", fake_run_entity):
        agui_router.attach_routes(r, workflow=MagicMock())
        endpoint = next(route.endpoint for route in r.routes if getattr(route, "path", "") == "/agui")
        response = await endpoint(request, MagicMock(run_id="r1"))
        chunks = [chunk async for chunk in response.body_iterator]

    assert len(chunks) == 2  # stopped at disconnect, not all 5


# ====== Fail-before reproductions: 4 confirmed bugs (RED on current gate) ======
# Each drives the real async_stream entrypoint with production event sequences.
# Synthetic WorkflowCompletedEvents carry realistic step_results so the provenance
# gate is genuinely exercised (the current endswith gate ignores step_results).


@pytest.mark.parametrize("value, expected", [(42, "42"), ([1, 2, 3], "[1, 2, 3]")])
@pytest.mark.asyncio
async def test_non_string_function_final_is_rendered_not_dropped(value, expected):
    # #2: a function final step returns a non-string; the engine keeps it raw in
    # WorkflowCompletedEvent.content. Must render (str for scalars, json.dumps for
    # list/dict), never drop (int -> get_text_from_message=="") or crash (list).
    events = await _collect(
        _stream(
            WorkflowCompletedEvent(
                content=value,
                step_results=[StepOutput(content=value, executor_type="function", step_type=StepType.STEP)],
                workflow_name="wf",
            )
        )
    )
    assert _deltas(events) == [expected]


@pytest.mark.asyncio
async def test_cancel_reason_is_not_rendered_as_the_answer():
    # H1: real cancel sequence (workflow.py:2865/2877) — partial content streams,
    # then WorkflowCancelledEvent(content=reason), then WorkflowCompletedEvent(
    # content=reason). The reason must NOT be rendered as the assistant's answer.
    reason = "Operation cancelled by user"
    events = await _collect(
        _stream(
            RunContentEvent(content="partial answer so far"),
            WorkflowCancelledEvent(reason=reason, content=reason, workflow_name="wf"),
            WorkflowCompletedEvent(content=reason, step_results=[], workflow_name="wf"),
        )
    )
    deltas = _deltas(events)
    assert "partial answer so far" in deltas
    assert reason not in deltas
    assert any(isinstance(e, CustomEvent) and e.name == "WorkflowCancelledEvent" for e in events)
    assert not any(e.type == ET.RUN_ERROR for e in events)
    assert events[-1].type == ET.RUN_FINISHED


@pytest.mark.asyncio
async def test_streamed_agent_final_after_tool_is_not_duplicated():
    # #7: an agent streams "part A. ", a tool closes the message, "part B." opens a
    # new one; completion consolidates "part A. part B.". The final leaf is an agent
    # (it streamed) -> the consolidation recap must be suppressed (no duplicate).
    tool = MagicMock()
    tool.tool_call_id = "t1"
    tool.tool_name = "x"
    tool.tool_args = {}
    tool.result = "ok"
    events = await _collect(
        _stream(
            RunContentEvent(content="part A. "),
            ToolCallStartedEvent(tool=tool),
            ToolCallCompletedEvent(tool=tool),
            RunContentEvent(content="part B."),
            WorkflowCompletedEvent(
                content="part A. part B.",
                step_results=[StepOutput(content="part A. part B.", executor_type="agent", step_type=StepType.STEP)],
                workflow_name="wf",
            ),
        )
    )
    deltas = _deltas(events)
    assert deltas.count("part A. part B.") == 0
    assert "part A. " in deltas
    assert "part B." in deltas


@pytest.mark.asyncio
async def test_streamed_final_then_empty_post_tool_chunk_is_not_duplicated():
    # C3: the final agent streams "FINAL", calls a tool (closing the message), then
    # emits an EMPTY / reasoning-only RunContentEvent (content=None) after the tool
    # -- which reopens a message. The answer already streamed, so the completion
    # recap must be suppressed; a per-message "streamed" signal would be reset by
    # the empty reopen and wrongly re-emit it (duplicate).
    tool = MagicMock()
    tool.tool_call_id = "t1"
    tool.tool_name = "x"
    tool.tool_args = {}
    tool.result = "ok"
    events = await _collect(
        _stream(
            RunContentEvent(content="FINAL"),
            ToolCallStartedEvent(tool=tool),
            ToolCallCompletedEvent(tool=tool),
            RunContentEvent(content=None),
            WorkflowCompletedEvent(
                content="FINAL",
                step_results=[StepOutput(content="FINAL", executor_type="agent", step_type=StepType.STEP)],
                workflow_name="wf",
            ),
        )
    )
    assert _deltas(events).count("FINAL") == 1


@pytest.mark.asyncio
async def test_short_non_streamed_final_is_not_dropped_by_suffix_match():
    # #4: an earlier step streamed "The result is 42"; the FINAL step is a function
    # returning "42" (a suffix of the streamed text). endswith dropped it; the
    # function-leaf provenance emits it.
    events = await _collect(
        _stream(
            RunContentEvent(content="The result is 42"),
            WorkflowCompletedEvent(
                content="42",
                step_results=[StepOutput(content="42", executor_type="function", step_type=StepType.STEP)],
                workflow_name="wf",
            ),
        )
    )
    assert "42" in _deltas(events)


@pytest.mark.asyncio
async def test_agent_final_not_streamed_is_emitted_not_dropped():
    # C1: stream_executor_events=False -- the agent's content lands in the
    # completion (leaf executor_type="agent") but NOTHING streamed to AG-UI.
    # Suppressing on the agent leaf alone silently DROPS the answer; the gate must
    # emit it (suppress only when something actually streamed).
    events = await _collect(
        _stream(
            WorkflowCompletedEvent(
                content="agent answer",
                step_results=[StepOutput(content="agent answer", executor_type="agent", step_type=StepType.STEP)],
                workflow_name="wf",
            )
        )
    )
    assert _deltas(events) == ["agent answer"]


@pytest.mark.asyncio
async def test_whitespace_only_final_content_is_not_emitted():
    # A final whose content renders to whitespace must not emit a junk TextMessage.
    events = await _collect(
        _stream(
            WorkflowCompletedEvent(
                content="   ",
                step_results=[StepOutput(content="   ", executor_type="function", step_type=StepType.STEP)],
                workflow_name="wf",
            )
        )
    )
    assert _deltas(events) == []
    assert not any(e.type == ET.TEXT_MESSAGE_START for e in events)


# ====== Provenance-shape matrix: descend-to-leaf decision per workflow shape ======
# True = final answer streamed (agent/team leaf) -> suppress recap.
# False = not streamed (function leaf) -> emit. None = uncertain -> emit (drop-safe).


def _so(executor_type, content="answer", step_type=StepType.STEP, steps=None):
    return StepOutput(content=content, executor_type=executor_type, step_type=step_type, steps=steps)


@pytest.mark.parametrize(
    "label, step_results, expected",
    [
        ("function", [_so("function")], False),
        ("multi-step function", [_so("function"), _so("function")], False),
        ("router->function", [_so(None, step_type=StepType.ROUTER, steps=[_so("function")])], False),
        ("router->agent", [_so(None, step_type=StepType.ROUTER, steps=[_so("agent")])], True),
        (
            "router->steps->agent (nested spine)",
            [_so(None, step_type=StepType.ROUTER, steps=[_so(None, step_type=StepType.STEPS, steps=[_so("agent")])])],
            True,
        ),
        ("agent", [_so("agent")], True),
        ("team", [_so("team")], True),
        (
            "parallel fan-out",
            [_so("parallel", step_type=StepType.PARALLEL, steps=[_so("function"), _so("function")])],
            None,
        ),
        ("loop fan-out", [_so("loop", step_type=StepType.LOOP, steps=[_so("agent")])], None),
        ("missing provenance", [], None),
        ("nested list (defensive)", [[_so("function")]], None),
    ],
)
def test_final_leaf_provenance_matrix(label, step_results, expected):
    chunk = WorkflowCompletedEvent(content="x", step_results=step_results, workflow_name="wf")
    assert _final_leaf_streamed(chunk) is expected


@pytest.mark.asyncio
async def test_router_function_leaf_emits_completion():
    # cookbook small-talk branch: Router -> chat (function). Non-streamed -> emit.
    rr = [_so(None, content="Hi there", step_type=StepType.ROUTER, steps=[_so("function", content="Hi there")])]
    events = await _collect(_stream(WorkflowCompletedEvent(content="Hi there", step_results=rr, workflow_name="wf")))
    assert _deltas(events) == ["Hi there"]


@pytest.mark.asyncio
async def test_router_agent_leaf_suppresses_completion():
    # cookbook research branch: Router -> [research, summarize] agents. Streamed -> suppress.
    rr = [
        _so(
            None,
            content="final summary",
            step_type=StepType.ROUTER,
            steps=[_so("agent", content="research"), _so("agent", content="final summary")],
        )
    ]
    events = await _collect(
        _stream(
            RunContentEvent(content="final summary"),
            WorkflowCompletedEvent(content="final summary", step_results=rr, workflow_name="wf"),
        )
    )
    assert _deltas(events).count("final summary") == 1


# ====== Real-engine C1 regression: stream_executor_events=False must not drop ======


class _StubModel(Model):
    """Offline model that yields a fixed assistant response (no network)."""

    def invoke(self, *args, **kwargs):
        return ModelResponse(role="assistant", content="stub answer")

    async def ainvoke(self, *args, **kwargs):
        return ModelResponse(role="assistant", content="stub answer")

    def invoke_stream(self, *args, **kwargs):
        yield ModelResponse(role="assistant", content="stub answer")

    async def ainvoke_stream(self, *args, **kwargs):
        yield ModelResponse(role="assistant", content="stub answer")

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.mark.parametrize("n_steps", [1, 2])
@pytest.mark.asyncio
async def test_stream_executor_events_false_delivers_final_answer_once(n_steps):
    # C1 regression, REAL engine: with stream_executor_events=False the agent's
    # content is filtered from the stream (nothing reaches the wire) but lands in
    # the completion with an agent leaf. The gate must deliver it exactly once,
    # across single- AND multi-step workflows (last_streamed_text stays empty).
    from agno.agent.agent import Agent
    from agno.workflow.step import Step
    from agno.workflow.workflow import Workflow

    steps = [Step(name="s%d" % i, agent=Agent(name="A%d" % i, model=_StubModel(id="stub"))) for i in range(n_steps)]
    wf = Workflow(name="w", steps=steps, stream_executor_events=False)
    events = [e async for e in run_entity(wf, _FakeRunInput())]
    assert _deltas(events).count("stub answer") == 1
    assert any(e.type == ET.RUN_FINISHED for e in events)
