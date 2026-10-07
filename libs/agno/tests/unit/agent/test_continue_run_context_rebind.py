"""Regression tests: continue_run re-points RunContext at the run that executes.

Continuing a COMPLETED run auto-forks a sibling with a fresh run_id, but the RunContext
is built before the fork. Left unbound, every tool, tool hook and reasoning step of the
continuation files its work under the PARENT run, session_state carries a stale
current_run_id, and a callable dependency resolved before the fork derives run-scoped
values from the parent's id. (#9681)

Driven through the real run/continue_run pipeline with a scripted offline model.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Iterator, List, Optional, Tuple, Union

import pytest

import agno.os.event_streams as es_mod
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.os.event_streams import InMemoryEventStream, set_event_stream
from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.agent import RunOutput
from agno.run.base import RunContext, RunStatus
from agno.run.team import TeamRunOutput
from agno.team import Team


class _ScriptedModel(Model):
    """Returns one scripted ModelResponse per provider call, in order.

    Deliberately duplicated per test file: the suite has no shared model stub, and each
    file's script is what the test is about.

    An Exception in the script is raised in its slot instead of returned, to
    script a transient provider failure.
    """

    def __init__(self, script: List[Union[ModelResponse, Exception]]) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0

    def __deepcopy__(self, memo: Any) -> "_ScriptedModel":
        return self  # one shared call counter, whatever the agent copies

    def _next(self) -> ModelResponse:
        response = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _tool_call(name: str, call_id: str, arguments: Optional[dict] = None) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        response_usage=MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15),
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments or {})},
            }
        ],
    )


def _text(content: str) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        content=content,
        response_usage=MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15),
    )


def _probe_script() -> List[ModelResponse]:
    return [
        _tool_call("probe_state", "call-1"),
        _text("first run done"),
        _tool_call("probe_state", "call-2"),
        _text("continuation done"),
    ]


def _retry_probe_script() -> List[Union[ModelResponse, Exception]]:
    """First run completes; the continuation's first attempt dies in the provider call
    and the retry runs the probe."""
    return [
        _tool_call("probe_state", "call-1"),
        _text("first run done"),
        RuntimeError("transient provider failure"),
        _tool_call("probe_state", "call-2"),
        _text("continuation done"),
    ]


def _in_place_retry_script() -> List[Union[ModelResponse, Exception]]:
    """First run completes; the continuation's first attempt dies in the provider call
    and the retry answers. No tool calls, so the message list is only what the
    dispatch itself appends."""
    return [
        _text("first run done"),
        RuntimeError("transient provider failure"),
        _text("continuation done"),
    ]


async def _execute(entity, *, async_mode: bool, stream: bool, continuing: bool = False, **kwargs):
    """Drive run/continue_run across the sync x async x stream matrix."""
    output_type = RunOutput if isinstance(entity, Agent) else TeamRunOutput
    if async_mode:
        method = entity.acontinue_run if continuing else entity.arun
        result = method(stream=stream, yield_run_output=stream, **kwargs)
        if stream:
            return [event async for event in result if isinstance(event, output_type)][-1]
        return await result

    method = entity.continue_run if continuing else entity.run
    result = method(stream=stream, yield_run_output=stream, **kwargs)
    if stream:
        return [event for event in result if isinstance(event, output_type)][-1]
    return result


def _run_id_probe(seen: List[dict]):
    def probe_state(run_context: Optional[RunContext] = None) -> str:
        """Record which run this call believes it belongs to."""
        state = (run_context.session_state or {}) if run_context else {}
        seen.append(
            {
                "context": run_context.run_id if run_context else None,
                "state": state.get("current_run_id"),
            }
        )
        return "probed"

    return probe_state


def _identity_probe(seen: List[dict]):
    def probe_state(run_context: Optional[RunContext] = None) -> str:
        """Record the identity keys."""
        state = (run_context.session_state or {}) if run_context else {}
        seen.append({k: state.get(k) for k in ("current_user_id", "current_session_id", "current_run_id")})
        return "probed"

    return probe_state


def _namespace_dependency(run_context: RunContext) -> str:
    """A run-scoped namespace derived from the run id."""
    return f"ns::{run_context.run_id}"


def _dependency_probe(seen: List[Tuple[Optional[str], Optional[str]]]):
    def probe_state(run_context: Optional[RunContext] = None) -> str:
        """Record the context run id and the resolved dependency together."""
        deps = (run_context.dependencies or {}) if run_context else {}
        seen.append((run_context.run_id if run_context else None, deps.get("ns")))
        return "probed"

    return probe_state


async def _drain_background_tasks(tasks) -> None:
    """The SSE generator returns when the producer pushes its sentinel, which happens before
    the event stream is finalized; wait for the detached task itself."""
    for _ in range(300):
        if not [t for t in list(tasks) if not t.done()]:
            return
        await asyncio.sleep(0.01)


@pytest.fixture()
def stream_harness():
    """Swap in a fresh in-memory event stream so a test can read what a background
    continue published under which run_id."""
    original = es_mod._event_stream
    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    set_event_stream(stream)
    yield stream
    es_mod._event_stream = original


class TestAgentContinuationRebind:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("async_mode", [False, True])
    @pytest.mark.parametrize("stream", [False, True])
    async def test_continuation_tools_see_the_forked_run_id(self, async_mode, stream, tmp_path):
        """Continuing a completed run forks a sibling with a fresh run_id; the tool called by
        the continuation must see the FORK's id on its run_context and in session_state, not
        the parent's."""
        seen: List[dict] = []
        agent = Agent(
            model=_ScriptedModel(_probe_script()),
            tools=[_run_id_probe(seen)],
            db=SqliteDb(db_file=str(tmp_path / "runid.db")),
            telemetry=False,
        )
        session_id = f"runid-{async_mode}-{stream}"
        first = await _execute(agent, async_mode=async_mode, stream=False, input="probe once", session_id=session_id)
        continued = await _execute(
            agent,
            async_mode=async_mode,
            stream=stream,
            continuing=True,
            run_id=first.run_id,
            session_id=session_id,
            input="probe again",
        )

        assert continued.run_id != first.run_id, "the continuation did not fork a sibling run"
        assert continued.forked_from_run_id == first.run_id
        assert len(seen) == 2
        assert seen[0]["context"] == first.run_id
        assert seen[1]["context"] == continued.run_id, f"the continuation's tool saw the parent run_id: {seen[1]}"
        # The sync dispatch re-stamps session_state after the modifiers, so this assertion
        # only bites on the async paths. Keep both arms.
        assert seen[1]["state"] == continued.run_id, f"session_state carried a stale current_run_id: {seen[1]}"

    @pytest.mark.asyncio
    async def test_the_rebind_restores_the_owner_and_session(self, tmp_path):
        """The identity keys are stripped before session_state is persisted, so a continuation
        that reloaded its state has lost them. The rebind puts them back, and must put back the
        values the run actually carries rather than whatever the context happens to hold."""
        seen: List[dict] = []
        agent = Agent(
            model=_ScriptedModel(_probe_script()),
            tools=[_identity_probe(seen)],
            db=SqliteDb(db_file=str(tmp_path / "ids.db")),
            telemetry=False,
        )
        first = agent.run("probe once", session_id="ids-1", user_id="owner-1")
        continued = agent.continue_run(run_id=first.run_id, session_id="ids-1", user_id="owner-1", input="probe again")

        assert len(seen) == 2
        for entry in seen:
            assert entry["current_user_id"] == "owner-1"
            assert entry["current_session_id"] == "ids-1"
        assert seen[0]["current_run_id"] == first.run_id
        assert seen[1]["current_run_id"] == continued.run_id

    @pytest.mark.asyncio
    async def test_an_in_place_continuation_keeps_the_run_id(self, tmp_path):
        """A run that is not COMPLETED continues in place, so there is no fork and the rebind
        must leave the run_id alone. The identity keys the reload dropped are back either way:
        the sync dispatch stamps them itself after the modifiers."""
        seen: List[dict] = []
        db_file = str(tmp_path / "inplace.db")
        agent = Agent(
            model=_ScriptedModel(_probe_script()),
            tools=[_identity_probe(seen)],
            db=SqliteDb(db_file=db_file),
            telemetry=False,
        )
        first = agent.run("probe once", session_id="inplace-1", user_id="owner-1")
        first.status = RunStatus.running

        # A second Agent over the same db, so the continuation really reloads the session
        # state that was persisted without the identity keys.
        resuming_agent = Agent(
            model=_ScriptedModel(_probe_script()[2:]),
            tools=[_identity_probe(seen)],
            db=SqliteDb(db_file=db_file),
            telemetry=False,
        )
        continued = resuming_agent.continue_run(run_response=first, session_id="inplace-1", user_id="owner-1")

        assert continued.run_id == first.run_id, "a non-COMPLETED run must continue in place, not fork"
        assert len(seen) == 2, f"expected one probe per model loop, got {seen}"
        assert seen[-1] == {
            "current_user_id": "owner-1",
            "current_session_id": "inplace-1",
            "current_run_id": first.run_id,
        }

    def test_the_rebind_cannot_blank_the_session_id(self):
        """`_initialize_session_state` guards session_id with `is not None`, which an empty
        string satisfies, so a context carrying "" would overwrite a good value with nothing."""
        from agno.agent._run import _bind_run_context_to_run

        context = RunContext(
            run_id="old",
            session_id="",
            user_id=None,
            session_state={"current_session_id": "GOOD", "current_user_id": "OWNER"},
        )
        _bind_run_context_to_run(context, RunOutput(run_id="new", session_id="s"))
        assert context.session_state["current_session_id"] == "GOOD"
        assert context.session_state["current_user_id"] == "OWNER"
        assert context.session_state["current_run_id"] == "new"
        assert context.run_id == "new"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("async_mode", [False, True])
    @pytest.mark.parametrize("stream", [False, True])
    async def test_callable_dependencies_resolve_against_the_forked_run(self, async_mode, stream):
        """A dependency factory may derive run-scoped values from run_context. Resolving
        before the continuation forks hands every factory the PARENT's run_id, so a
        run-scoped namespace, audit client or output path files the continuation's work
        under the run before it — and disagrees with the run_id the tool in the same
        attempt sees."""
        seen: List[Tuple[Optional[str], Optional[str]]] = []
        agent = Agent(
            model=_ScriptedModel(_probe_script()),
            tools=[_dependency_probe(seen)],
            dependencies={"ns": _namespace_dependency},
            telemetry=False,
        )
        first = await _execute(agent, async_mode=async_mode, stream=False, input="probe once")
        continued = await _execute(
            agent, async_mode=async_mode, stream=stream, continuing=True, run_response=first, input="probe again"
        )

        assert continued.run_id != first.run_id
        assert len(seen) == 2
        for run_output, (context_run_id, dependency) in zip((first, continued), seen):
            expected = run_output.run_id
            assert context_run_id == expected
            assert dependency == f"ns::{expected}", f"run {expected}: dependency resolved against {dependency}"

    @pytest.mark.asyncio
    async def test_a_non_callable_dependency_is_untouched_by_the_reordering(self):
        seen: List[Tuple[Any, Any]] = []

        def probe_state(run_context: Optional[RunContext] = None) -> str:
            """Record a plain dependency value."""
            deps = (run_context.dependencies or {}) if run_context else {}
            seen.append((deps.get("plain"), deps.get("nested")))
            return "probed"

        agent = Agent(
            model=_ScriptedModel(_probe_script()),
            tools=[probe_state],
            dependencies={"plain": "a literal", "nested": {"k": [1, 2]}},
            telemetry=False,
        )
        first = agent.run("probe once")
        agent.continue_run(run_response=first, input="probe again")
        assert seen == [("a literal", {"k": [1, 2]})] * 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stream", [False, True])
    async def test_async_continue_retry_resolves_dependencies_against_the_executing_fork(self, stream):
        """A transient model failure re-enters the retry loop, which forks AGAIN — the first
        fork is abandoned. The dependency factories were already consumed against the
        abandoned fork, so without re-resolving from the unresolved values the run that
        actually completes executes with the abandoned fork's dependency."""
        seen: List[Tuple[Optional[str], Optional[str]]] = []
        agent = Agent(
            model=_ScriptedModel(_retry_probe_script()),
            tools=[_dependency_probe(seen)],
            dependencies={"ns": _namespace_dependency},
            retries=1,
            delay_between_retries=0,
            telemetry=False,
        )
        first = agent.run("probe once")
        continued = await _execute(
            agent, async_mode=True, stream=stream, continuing=True, run_response=first, input="probe again"
        )

        assert continued.run_id != first.run_id
        assert continued.forked_from_run_id == first.run_id, (
            f"the retry forked the abandoned attempt instead of the parent: {continued.forked_from_run_id}"
        )
        assert len(seen) == 2, f"expected one probe per completed model loop, got {seen}"
        context_run_id, dependency = seen[1]
        assert context_run_id == continued.run_id
        assert dependency == f"ns::{continued.run_id}", (
            f"the completing run {continued.run_id} executed with a dependency scoped to an abandoned fork: {dependency}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stream", [False, True])
    async def test_an_in_place_async_retry_appends_the_input_once(self, stream):
        """A non-COMPLETED run continues in place, so a transient failure re-enters the
        retry loop with the SAME run_response. The follow-up ``input`` was already
        appended by the first attempt; the retry must not append it again."""
        agent = Agent(
            model=_ScriptedModel(_in_place_retry_script()),
            retries=1,
            delay_between_retries=0,
            telemetry=False,
        )
        first = agent.run("probe once")
        first.status = RunStatus.error
        continued = await _execute(
            agent, async_mode=True, stream=stream, continuing=True, run_response=first, input="follow-up"
        )

        assert continued.run_id == first.run_id, "an ERROR run must continue in place, not fork"
        assert continued.status == RunStatus.completed
        user_messages = [m.content for m in continued.messages or [] if m.role == "user"]
        assert user_messages == ["probe once", "follow-up"], f"the retry re-appended the follow-up: {user_messages}"

    @pytest.mark.asyncio
    async def test_a_background_stream_continue_of_a_cancelled_run_leaves_the_row_alone(self, tmp_path):
        """A cancelled run is refused downstream. The background streamer never took the
        source row over, so the refusal must not stamp ERROR over it on the way out — and
        the refusal is an answer, so the client gets a RunError frame, not an empty body."""
        from agno.agent._session import asave_run

        db = SqliteDb(db_file=str(tmp_path / "bg.db"))
        agent = Agent(model=_ScriptedModel([_text("first run done")]), db=db, telemetry=False)
        first = await agent.arun("probe once", session_id="bg-1")
        first.status = RunStatus.cancelled
        await asave_run(agent, run=first, session_id="bg-1")

        frames = [
            chunk
            async for chunk in agent.acontinue_run(
                run_id=first.run_id, session_id="bg-1", input="probe again", stream=True, background=True
            )
        ]

        stored = db.get_session(session_id="bg-1", session_type="agent")
        assert stored is not None and stored.runs is not None
        assert [r.status for r in stored.runs if r.run_id == first.run_id] == [RunStatus.cancelled], (
            "the refused continue rewrote the source run's status"
        )
        assert len(stored.runs) == 1, "a refused continue must not persist a second run"
        assert frames and "event: RunError" in frames[0], f"expected a RunError frame, got {frames[:1]}"

    @pytest.mark.asyncio
    async def test_a_background_stream_continue_of_a_missing_run_registers_nothing(self, stream_harness, tmp_path):
        """No stored row means no source run to take over and none to advertise: the
        producer must not register the key at all, or a run that never existed is
        advertised to reconnecting clients. The refusal still reaches the client."""
        from agno.agent._run import _background_tasks

        agent = Agent(
            model=_ScriptedModel([_text("never called")]),
            db=SqliteDb(db_file=str(tmp_path / "bg-missing.db")),
            telemetry=False,
        )

        frames = [
            chunk
            async for chunk in agent.acontinue_run(
                run_id="r-missing", session_id="bg-3", input="probe again", stream=True, background=True
            )
        ]
        await _drain_background_tasks(_background_tasks)

        assert frames and "event: RunError" in frames[0], f"expected a RunError frame, got {frames[:1]}"
        assert await stream_harness.get_run_status("r-missing") is None, (
            "a run missing from the session was registered on the event stream"
        )

    @pytest.mark.asyncio
    async def test_a_background_stream_continue_of_a_completed_run_is_published_under_the_fork(
        self, stream_harness, tmp_path
    ):
        """A background continue of a COMPLETED run auto-forks. Every event-stream write goes
        under the fork's own id, so /resume on the fork replays it and /resume on the parent
        never replays a run the parent did not execute."""
        db = SqliteDb(db_file=str(tmp_path / "bg-fork.db"))
        agent = Agent(
            model=_ScriptedModel([_text("first run done"), _text("continuation done")]), db=db, telemetry=False
        )
        first = await agent.arun("probe once", session_id="bg-2")
        assert first.status == RunStatus.completed

        from agno.agent._run import _background_tasks

        frames = [
            chunk
            async for chunk in agent.acontinue_run(
                run_id=first.run_id, session_id="bg-2", input="probe again", stream=True, background=True
            )
        ]
        await _drain_background_tasks(_background_tasks)

        assert frames, "the client received no frames"
        assert await stream_harness.get_run_status(first.run_id) is None, "the parent's key was written for a fork"
        stored = db.get_session(session_id="bg-2", session_type="agent")
        assert stored is not None and stored.runs is not None and len(stored.runs) == 2
        assert [r.status for r in stored.runs if r.run_id == first.run_id] == [RunStatus.completed]
        fork_id = next(r.run_id for r in stored.runs if r.forked_from_run_id == first.run_id)
        assert await stream_harness.get_run_status(fork_id) == RunStatus.completed
        assert await stream_harness.get_event_count(fork_id) == len(frames), (
            "the fork's events were not buffered under the fork's own key"
        )

    @pytest.mark.asyncio
    async def test_a_background_stream_forking_retry_re_forks_under_the_same_id(self, stream_harness, tmp_path):
        """The fork id is minted before the first attempt, so a transient failure that
        re-enters the retry loop re-forks under that same id: the key the stream registered
        is the one that completes, and the session holds one fork, not one per attempt."""
        db = SqliteDb(db_file=str(tmp_path / "bg-retry.db"))
        agent = Agent(
            model=_ScriptedModel(_in_place_retry_script()),
            db=db,
            retries=1,
            delay_between_retries=0,
            telemetry=False,
        )
        first = await agent.arun("probe once", session_id="bg-4")
        assert first.status == RunStatus.completed

        from agno.agent._run import _background_tasks

        frames = [
            chunk
            async for chunk in agent.acontinue_run(
                run_id=first.run_id, session_id="bg-4", input="probe again", stream=True, background=True
            )
        ]
        await _drain_background_tasks(_background_tasks)

        assert frames, "the client received no frames"
        stored = db.get_session(session_id="bg-4", session_type="agent")
        assert stored is not None and stored.runs is not None
        forks = [r for r in stored.runs if r.forked_from_run_id == first.run_id]
        assert [r.status for r in forks] == [RunStatus.completed], (
            f"expected one completed fork, got {[(r.run_id, r.status) for r in forks]}"
        )
        assert await stream_harness.get_run_status(forks[0].run_id) == RunStatus.completed, (
            "the retry executed under a different id than the one the stream registered"
        )

    @pytest.mark.asyncio
    async def test_a_background_stream_continue_of_an_unsaved_run_response_is_buffered_under_its_id(
        self, stream_harness, tmp_path
    ):
        """A caller-held run whose row is not in this agent's db still executes: the dispatch
        continues the object and never reads the row. Its events must still be buffered under
        its id, or the background continue cannot be reconnected."""
        from agno.agent._run import _background_tasks

        first = await Agent(model=_ScriptedModel([_text("first run done")]), telemetry=False).arun("probe once")
        first.status = RunStatus.error
        agent = Agent(
            model=_ScriptedModel([_text("continuation done")]),
            db=SqliteDb(db_file=str(tmp_path / "bg-unsaved.db")),
            telemetry=False,
        )

        frames = [
            chunk
            async for chunk in agent.acontinue_run(
                run_response=first, session_id="bg-5", input="probe again", stream=True, background=True
            )
        ]
        await _drain_background_tasks(_background_tasks)

        assert frames, "the client received no frames"
        assert await stream_harness.get_run_status(first.run_id) == RunStatus.completed
        assert await stream_harness.get_event_count(first.run_id) == len(frames), (
            "the continuation executed but none of its events were buffered"
        )

    @pytest.mark.asyncio
    async def test_a_background_stream_continue_of_a_stale_object_is_buffered_where_it_executes(
        self, stream_harness, tmp_path
    ):
        """The dispatch decides fork-or-not from the caller's object, not the stored row. A
        PAUSED object over a COMPLETED row continues in place, so its events belong under the
        source id; a fork id predicted from the row would name a run that never executes."""
        from copy import deepcopy

        from agno.agent._run import _background_tasks

        db = SqliteDb(db_file=str(tmp_path / "bg-stale.db"))
        agent = Agent(
            model=_ScriptedModel([_text("first run done"), _text("continuation done")]), db=db, telemetry=False
        )
        first = await agent.arun("probe once", session_id="bg-6")
        stale = deepcopy(first)
        stale.status = RunStatus.paused

        frames = [
            chunk
            async for chunk in agent.acontinue_run(
                run_response=stale, session_id="bg-6", input="probe again", stream=True, background=True
            )
        ]
        await _drain_background_tasks(_background_tasks)

        assert frames, "the client received no frames"
        stored = db.get_session(session_id="bg-6", session_type="agent")
        assert stored is not None and stored.runs is not None
        assert [r.run_id for r in stored.runs] == [first.run_id], "the continue was expected to run in place"
        assert await stream_harness.get_event_count(first.run_id) == len(frames), (
            "the events were buffered under an id that never executed"
        )

    @pytest.mark.asyncio
    async def test_a_background_stream_continue_of_a_completed_object_over_a_cancelled_row_is_buffered_under_the_fork(
        self, stream_harness, tmp_path
    ):
        """The dispatch refuses only when the run it continues is cancelled. A COMPLETED object
        over a CANCELLED row forks, so the fork's events must be buffered under the fork id."""
        from copy import deepcopy

        from agno.agent._run import _background_tasks
        from agno.agent._session import asave_run

        db = SqliteDb(db_file=str(tmp_path / "bg-cancelled-row.db"))
        agent = Agent(
            model=_ScriptedModel([_text("first run done"), _text("continuation done")]), db=db, telemetry=False
        )
        first = await agent.arun("probe once", session_id="bg-7")
        held = deepcopy(first)
        first.status = RunStatus.cancelled
        await asave_run(agent, run=first, session_id="bg-7")

        frames = [
            chunk
            async for chunk in agent.acontinue_run(
                run_response=held, session_id="bg-7", input="probe again", stream=True, background=True
            )
        ]
        await _drain_background_tasks(_background_tasks)

        stored = db.get_session(session_id="bg-7", session_type="agent")
        assert stored is not None and stored.runs is not None
        forks = [r for r in stored.runs if r.forked_from_run_id == first.run_id]
        assert len(forks) == 1, "the continue was expected to fork the completed object"
        assert await stream_harness.get_event_count(forks[0].run_id) == len(frames), (
            "the fork executed but none of its events were buffered"
        )
        assert await stream_harness.get_run_status(first.run_id) is None

    @pytest.mark.asyncio
    async def test_a_forking_retry_before_the_fork_keeps_the_parents_cancellation_entry(self, monkeypatch, tmp_path):
        """When the first attempt dies before it forks, run_response still names the parent.
        The retry drops only a fork it abandoned; dropping the parent's entry would make a
        live parent uncancellable."""
        import agno.agent._storage as storage
        from agno.run.cancel import acleanup_run, aget_active_runs, aregister_run

        agent = Agent(
            model=_ScriptedModel([_text("first run done"), _text("continuation done")]),
            db=SqliteDb(db_file=str(tmp_path / "retry-parent.db")),
            retries=1,
            delay_between_retries=0,
            telemetry=False,
        )
        first = await agent.arun("probe once", session_id="rp-1")
        await aregister_run(first.run_id)

        real_read = storage.aread_or_create_session
        reads = {"n": 0}

        async def flaky_read(*args: Any, **kwargs: Any):
            reads["n"] += 1
            if reads["n"] == 1:
                raise ConnectionError("transient db failure")
            return await real_read(*args, **kwargs)

        monkeypatch.setattr(storage, "aread_or_create_session", flaky_read)
        continued = await _execute(
            agent,
            async_mode=True,
            stream=True,
            continuing=True,
            run_id=first.run_id,
            session_id="rp-1",
            fork=True,
            input="probe again",
        )

        assert continued.run_id != first.run_id and continued.status == RunStatus.completed
        still_registered = first.run_id in await aget_active_runs()
        await acleanup_run(first.run_id)
        assert still_registered, "the retry dropped the parent's cancellation entry"

    @pytest.mark.asyncio
    async def test_a_stream_retry_before_the_run_loads_still_forks_the_stored_run(self, monkeypatch, tmp_path):
        """When the first attempt of a streamed continue fails before the run is loaded, the
        retry must load the stored run and fork it. An error placeholder left in run_response
        was continued in place instead, and the parent row was lost."""
        db = SqliteDb(db_file=str(tmp_path / "stream-retry-load.db"))
        agent = Agent(
            model=_ScriptedModel([_text("first run done"), _text("continuation done")]),
            db=db,
            retries=1,
            delay_between_retries=0,
            telemetry=False,
        )
        first = await agent.arun("probe once", session_id="sr-1")

        real_get_session = db.get_session
        reads = {"n": 0}

        def flaky_get_session(*args: Any, **kwargs: Any):
            reads["n"] += 1
            if reads["n"] == 2:
                raise ConnectionError("transient db failure")
            return real_get_session(*args, **kwargs)

        monkeypatch.setattr(db, "get_session", flaky_get_session)
        continued = await _execute(
            agent, async_mode=True, stream=True, continuing=True, run_id=first.run_id, session_id="sr-1", input="again"
        )
        monkeypatch.setattr(db, "get_session", real_get_session)

        assert continued.forked_from_run_id == first.run_id, "the retry continued a placeholder instead of forking"
        stored = db.get_session(session_id="sr-1", session_type="agent")
        assert stored is not None and stored.runs is not None
        assert [len(r.messages or []) for r in stored.runs if r.run_id == first.run_id] == [
            len(first.messages or [])
        ], "the parent run was overwritten or lost"


class TestTeamContinuationRebind:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("async_mode", [False, True])
    @pytest.mark.parametrize("stream", [False, True])
    async def test_continuation_rebinds_context_and_dependencies(self, async_mode, stream):
        """The team twin: continuing a completed team run forks a sibling, and the leader's
        tools and callable dependencies must see the fork's run_id."""
        seen: List[Tuple[Optional[str], Optional[str]]] = []
        member = Agent(name="member", model=_ScriptedModel([_text("member done")]), telemetry=False)
        team = Team(
            members=[member],
            model=_ScriptedModel(_probe_script()),
            tools=[_dependency_probe(seen)],
            dependencies={"ns": _namespace_dependency},
            telemetry=False,
        )
        first = await _execute(team, async_mode=async_mode, stream=False, input="probe once")
        continued = await _execute(
            team, async_mode=async_mode, stream=stream, continuing=True, run_response=first, input="probe again"
        )

        assert continued.run_id != first.run_id, "the team continuation did not fork a sibling run"
        assert len(seen) == 2
        for run_output, (context_run_id, dependency) in zip((first, continued), seen):
            expected = run_output.run_id
            assert context_run_id == expected
            assert dependency == f"ns::{expected}", f"team run {expected}: dependency resolved against {dependency}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stream", [False, True])
    async def test_async_continue_retry_resolves_dependencies_against_the_executing_fork(self, stream):
        """The team twin of the agent retry test above."""
        seen: List[Tuple[Optional[str], Optional[str]]] = []
        member = Agent(name="member", model=_ScriptedModel([_text("member done")]), telemetry=False)
        team = Team(
            members=[member],
            model=_ScriptedModel(_retry_probe_script()),
            tools=[_dependency_probe(seen)],
            dependencies={"ns": _namespace_dependency},
            retries=1,
            delay_between_retries=0,
            telemetry=False,
        )
        first = team.run("probe once")
        continued = await _execute(
            team, async_mode=True, stream=stream, continuing=True, run_response=first, input="probe again"
        )

        assert continued.run_id != first.run_id
        assert continued.forked_from_run_id == first.run_id, (
            f"the retry forked the abandoned attempt instead of the parent: {continued.forked_from_run_id}"
        )
        assert len(seen) == 2, f"expected one probe per completed model loop, got {seen}"
        context_run_id, dependency = seen[1]
        assert context_run_id == continued.run_id
        assert dependency == f"ns::{continued.run_id}", (
            f"the completing team run {continued.run_id} executed with a dependency scoped to "
            f"an abandoned fork: {dependency}"
        )

    def test_the_rebind_cannot_blank_the_session_id(self):
        from agno.team._run import _bind_run_context_to_team_run

        member = Agent(name="member", model=_ScriptedModel([_text("x")]), telemetry=False)
        team = Team(members=[member], model=_ScriptedModel([_text("x")]), telemetry=False)
        context = RunContext(
            run_id="old",
            session_id="",
            user_id=None,
            session_state={"current_session_id": "GOOD", "current_user_id": "OWNER"},
        )
        _bind_run_context_to_team_run(team, context, TeamRunOutput(run_id="new", session_id="s"))
        assert context.session_state["current_session_id"] == "GOOD"
        assert context.session_state["current_user_id"] == "OWNER"
        assert context.session_state["current_run_id"] == "new"
        assert context.run_id == "new"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stream", [False, True])
    async def test_an_in_place_async_retry_appends_the_input_once(self, stream):
        """The team twin of the agent test above."""
        member = Agent(name="member", model=_ScriptedModel([_text("member done")]), telemetry=False)
        team = Team(
            members=[member],
            model=_ScriptedModel(_in_place_retry_script()),
            retries=1,
            delay_between_retries=0,
            telemetry=False,
        )
        first = team.run("probe once")
        first.status = RunStatus.error
        continued = await _execute(
            team, async_mode=True, stream=stream, continuing=True, run_response=first, input="follow-up"
        )

        assert continued.run_id == first.run_id, "an ERROR team run must continue in place, not fork"
        assert continued.status == RunStatus.completed
        user_messages = [m.content for m in continued.messages or [] if m.role == "user"]
        assert user_messages == ["probe once", "follow-up"], f"the retry re-appended the follow-up: {user_messages}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("async_mode", [False, True])
    async def test_a_member_run_does_not_overwrite_the_team_identity_keys(self, async_mode):
        """A member runs under its own run_id and stamps its own current_run_id into the
        session_state copy it was handed. Merging that copy back must carry the member's
        real writes into the team's state and leave the team's identity keys alone — a
        leader tool called after the delegation must still see the TEAM's run_id."""
        seen: List[dict] = []

        def member_probe(run_context: Optional[RunContext] = None) -> str:
            """Write a real key into the member's session_state."""
            if run_context is not None and run_context.session_state is not None:
                run_context.session_state["member_note"] = "written by the member"
            return "noted"

        def leader_probe(run_context: Optional[RunContext] = None) -> str:
            """Record the team's session_state as the leader sees it after the delegation."""
            seen.append(dict(run_context.session_state or {}) if run_context else {})
            return "probed"

        member = Agent(
            id="member",
            name="member",
            model=_ScriptedModel([_tool_call("member_probe", "call-m"), _text("member done")]),
            tools=[member_probe],
            telemetry=False,
        )
        team = Team(
            members=[member],
            model=_ScriptedModel(
                [
                    _tool_call("delegate_task_to_member", "call-1", {"member_id": "member", "task": "probe"}),
                    _tool_call("leader_probe", "call-2"),
                    _text("team done"),
                ]
            ),
            tools=[leader_probe],
            session_state={},
            telemetry=False,
        )
        run = await _execute(team, async_mode=async_mode, stream=False, input="delegate then probe")

        assert run.status == RunStatus.completed
        assert len(seen) == 1, f"expected the leader probe once, got {seen}"
        assert seen[0].get("member_note") == "written by the member", f"the member's write did not merge: {seen[0]}"
        assert seen[0].get("current_run_id") == run.run_id, (
            f"the leader's tool saw the member's run_id in session_state after the delegation: {seen[0]}"
        )

    @pytest.mark.asyncio
    async def test_a_background_stream_continue_of_a_completed_run_is_published_under_the_fork(
        self, stream_harness, tmp_path
    ):
        """The team twin of the agent test above."""
        db = SqliteDb(db_file=str(tmp_path / "bg-fork-team.db"))
        member = Agent(name="member", model=_ScriptedModel([_text("member done")]), telemetry=False)
        team = Team(
            members=[member],
            model=_ScriptedModel([_text("first run done"), _text("continuation done")]),
            db=db,
            telemetry=False,
        )
        first = await team.arun("probe once", session_id="bg-2")
        assert first.status == RunStatus.completed

        from agno.team._run import _background_tasks

        frames = [
            chunk
            async for chunk in team.acontinue_run(
                run_id=first.run_id, session_id="bg-2", input="probe again", stream=True, background=True
            )
        ]
        await _drain_background_tasks(_background_tasks)

        assert frames, "the client received no frames"
        assert await stream_harness.get_run_status(first.run_id) is None, "the parent's key was written for a fork"
        stored = db.get_session(session_id="bg-2", session_type="team")
        assert stored is not None and stored.runs is not None
        assert [r.status for r in stored.runs if r.run_id == first.run_id] == [RunStatus.completed]
        fork_id = next(r.run_id for r in stored.runs if r.forked_from_run_id == first.run_id)
        assert await stream_harness.get_run_status(fork_id) == RunStatus.completed
        assert await stream_harness.get_event_count(fork_id) == len(frames), (
            "the fork's events were not buffered under the fork's own key"
        )

    @pytest.mark.asyncio
    async def test_a_background_stream_forking_retry_re_forks_under_the_same_id(self, stream_harness, tmp_path):
        """The team twin of the agent test above."""
        db = SqliteDb(db_file=str(tmp_path / "bg-retry-team.db"))
        member = Agent(name="member", model=_ScriptedModel([_text("member done")]), telemetry=False)
        team = Team(
            members=[member],
            model=_ScriptedModel(_in_place_retry_script()),
            db=db,
            retries=1,
            delay_between_retries=0,
            telemetry=False,
        )
        first = await team.arun("probe once", session_id="bg-4")
        assert first.status == RunStatus.completed

        from agno.team._run import _background_tasks

        frames = [
            chunk
            async for chunk in team.acontinue_run(
                run_id=first.run_id, session_id="bg-4", input="probe again", stream=True, background=True
            )
        ]
        await _drain_background_tasks(_background_tasks)

        assert frames, "the client received no frames"
        stored = db.get_session(session_id="bg-4", session_type="team")
        assert stored is not None and stored.runs is not None
        forks = [r for r in stored.runs if r.forked_from_run_id == first.run_id]
        assert [r.status for r in forks] == [RunStatus.completed], (
            f"expected one completed fork, got {[(r.run_id, r.status) for r in forks]}"
        )
        assert await stream_harness.get_run_status(forks[0].run_id) == RunStatus.completed, (
            "the retry executed under a different id than the one the stream registered"
        )

    @pytest.mark.asyncio
    async def test_a_background_stream_continue_of_a_missing_run_registers_nothing(self, stream_harness, tmp_path):
        """The team twin of the agent test above."""
        from agno.team._run import _background_tasks

        member = Agent(name="member", model=_ScriptedModel([_text("never called")]), telemetry=False)
        team = Team(
            members=[member],
            model=_ScriptedModel([_text("never called")]),
            db=SqliteDb(db_file=str(tmp_path / "bg-missing-team.db")),
            telemetry=False,
        )

        frames = [
            chunk
            async for chunk in team.acontinue_run(
                run_id="r-missing", session_id="bg-3", input="probe again", stream=True, background=True
            )
        ]
        await _drain_background_tasks(_background_tasks)

        assert frames and "RunError" in frames[0], f"expected a RunError frame, got {frames[:1]}"
        assert await stream_harness.get_run_status("r-missing") is None, (
            "a run missing from the session was registered on the event stream"
        )

    @pytest.mark.asyncio
    async def test_a_stream_retry_before_the_run_loads_still_forks_the_stored_run(self, monkeypatch, tmp_path):
        """The team twin of the agent test above."""
        db = SqliteDb(db_file=str(tmp_path / "stream-retry-load-team.db"))
        member = Agent(name="member", model=_ScriptedModel([_text("member done")]), telemetry=False)
        team = Team(
            members=[member],
            model=_ScriptedModel([_text("first run done"), _text("continuation done")]),
            db=db,
            retries=1,
            delay_between_retries=0,
            telemetry=False,
        )
        first = await team.arun("probe once", session_id="sr-2")

        real_get_session = db.get_session
        reads = {"n": 0}

        def flaky_get_session(*args: Any, **kwargs: Any):
            reads["n"] += 1
            if reads["n"] == 2:
                raise ConnectionError("transient db failure")
            return real_get_session(*args, **kwargs)

        monkeypatch.setattr(db, "get_session", flaky_get_session)
        continued = await _execute(
            team, async_mode=True, stream=True, continuing=True, run_id=first.run_id, session_id="sr-2", input="again"
        )
        monkeypatch.setattr(db, "get_session", real_get_session)

        assert continued.forked_from_run_id == first.run_id, "the retry continued a placeholder instead of forking"
        stored = db.get_session(session_id="sr-2", session_type="team")
        assert stored is not None and stored.runs is not None
        assert [len(r.messages or []) for r in stored.runs if r.run_id == first.run_id] == [
            len(first.messages or [])
        ], "the parent run was overwritten or lost"
