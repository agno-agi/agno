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

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.team import Team


class ScriptedModel(Model):
    """Returns one scripted ModelResponse per provider call, in order.

    An Exception in the script is raised in its slot instead of returned, to
    script a transient provider failure.
    """

    def __init__(self, script: List[Union[ModelResponse, Exception]]) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0

    def __deepcopy__(self, memo: Any) -> "ScriptedModel":
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


def _tool_call(name: str, call_id: str) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps({})},
            }
        ],
    )


def _text(content: str) -> ModelResponse:
    return ModelResponse(role="assistant", content=content)


def _probe_script() -> List[ModelResponse]:
    return [
        _tool_call("probe_state", "call-1"),
        _text("first run done"),
        _tool_call("probe_state", "call-2"),
        _text("continuation done"),
    ]


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


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_continuation_tools_see_the_forked_run_id(mode, tmp_path):
    """Continuing a completed run forks a sibling with a fresh run_id; the tool called by
    the continuation must see the FORK's id on its run_context and in session_state, not
    the parent's."""
    seen: List[dict] = []
    agent = Agent(
        model=ScriptedModel(_probe_script()),
        tools=[_run_id_probe(seen)],
        db=SqliteDb(db_file=str(tmp_path / "runid.db")),
    )
    session_id = f"runid-{mode}"
    if mode == "sync":
        first = agent.run("probe once", session_id=session_id)
        continued = agent.continue_run(
            run_id=first.run_id,
            session_id=session_id,
            input="probe again",
            session_state={"seed": True},
        )
    else:
        first = agent.run("probe once", session_id=session_id)
        continued = asyncio.run(agent.acontinue_run(run_id=first.run_id, session_id=session_id, input="probe again"))

    assert continued.run_id != first.run_id, "the continuation did not fork a sibling run"
    assert continued.forked_from_run_id == first.run_id
    assert len(seen) == 2
    assert seen[0]["context"] == first.run_id
    assert seen[1]["context"] == continued.run_id, f"the continuation's tool saw the parent run_id: {seen[1]}"
    assert seen[1]["state"] == continued.run_id, f"session_state carried a stale current_run_id: {seen[1]}"


def test_the_rebind_leaves_the_owner_and_session_alone(tmp_path):
    """Re-pointing the context at the forked run must not rewrite current_user_id or
    current_session_id: those are already right on a continuation, and overwriting them
    from whatever the context happens to carry can only lose information."""
    seen: List[dict] = []

    def probe_state(run_context: Optional[RunContext] = None) -> str:
        """Record the identity keys."""
        state = (run_context.session_state or {}) if run_context else {}
        seen.append({k: state.get(k) for k in ("current_user_id", "current_session_id", "current_run_id")})
        return "probed"

    agent = Agent(
        model=ScriptedModel(_probe_script()),
        tools=[probe_state],
        db=SqliteDb(db_file=str(tmp_path / "ids.db")),
    )
    first = agent.run("probe once", session_id="ids-1", user_id="owner-1")
    continued = agent.continue_run(
        run_id=first.run_id,
        session_id="ids-1",
        user_id="owner-1",
        input="probe again",
        session_state={"seed": True},
    )
    assert len(seen) == 2
    # Whatever the identity keys hold, the continuation must hold the same: the rebind's
    # job is the run_id and nothing else.
    assert seen[1]["current_user_id"] == seen[0]["current_user_id"]
    assert seen[1]["current_session_id"] == seen[0]["current_session_id"]
    # ... and the run_id is the one thing it does move.
    assert seen[0]["current_run_id"] == first.run_id
    assert seen[1]["current_run_id"] == continued.run_id
    assert seen[0]["current_run_id"] != seen[1]["current_run_id"]


def test_the_rebind_cannot_blank_the_session_id():
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


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_callable_dependencies_resolve_against_the_forked_run(mode):
    """A dependency factory may derive run-scoped values from run_context. Resolving
    before the continuation forks hands every factory the PARENT's run_id, so a
    run-scoped namespace, audit client or output path files the continuation's work
    under the run before it — and disagrees with the run_id the tool in the same
    attempt sees."""
    seen: List[Tuple[Optional[str], Optional[str]]] = []
    agent = Agent(
        model=ScriptedModel(_probe_script()),
        tools=[_dependency_probe(seen)],
        dependencies={"ns": _namespace_dependency},
    )
    if mode == "sync":
        first = agent.run("probe once")
        continued = agent.continue_run(run_response=first, input="probe again")
    else:
        first = agent.run("probe once")
        continued = asyncio.run(agent.acontinue_run(run_response=first, input="probe again"))

    assert continued.run_id != first.run_id
    assert len(seen) == 2
    for run_output, (context_run_id, dependency) in zip((first, continued), seen):
        expected = run_output.run_id
        assert context_run_id == expected
        assert dependency == f"ns::{expected}", f"run {expected}: dependency resolved against {dependency}"


def test_a_non_callable_dependency_is_untouched_by_the_reordering():
    seen: List[Tuple[Any, Any]] = []

    def probe_state(run_context: Optional[RunContext] = None) -> str:
        """Record a plain dependency value."""
        deps = (run_context.dependencies or {}) if run_context else {}
        seen.append((deps.get("plain"), deps.get("nested")))
        return "probed"

    agent = Agent(
        model=ScriptedModel(_probe_script()),
        tools=[probe_state],
        dependencies={"plain": "a literal", "nested": {"k": [1, 2]}},
    )
    first = agent.run("probe once")
    agent.continue_run(run_response=first, input="probe again")
    assert seen == [("a literal", {"k": [1, 2]})] * 2


def test_team_continuation_rebinds_context_and_dependencies():
    """The team twin: continuing a completed team run forks a sibling, and the leader's
    tools and callable dependencies must see the fork's run_id."""
    seen: List[Tuple[Optional[str], Optional[str]]] = []
    member = Agent(name="member", model=ScriptedModel([_text("member done")]))
    team = Team(
        members=[member],
        model=ScriptedModel(_probe_script()),
        tools=[_dependency_probe(seen)],
        dependencies={"ns": _namespace_dependency},
    )
    first = team.run("probe once")
    continued = team.continue_run(run_response=first, input="probe again")

    assert continued.run_id != first.run_id, "the team continuation did not fork a sibling run"
    assert len(seen) == 2
    for run_output, (context_run_id, dependency) in zip((first, continued), seen):
        expected = run_output.run_id
        assert context_run_id == expected
        assert dependency == f"ns::{expected}", f"team run {expected}: dependency resolved against {dependency}"


@pytest.mark.parametrize("mode", ["async", "async_stream"])
def test_team_async_continuation_rebinds_context_and_dependencies(mode):
    """The async team twins: acontinue_run resolves dependencies through _asetup_session,
    which runs before the continuation forks. Resolving there hands every factory the
    PARENT's run_id, so the leader's tool sees run_id=child paired with a parent-scoped
    dependency."""
    from agno.run.team import TeamRunOutput

    seen: List[Tuple[Optional[str], Optional[str]]] = []
    member = Agent(name="member", model=ScriptedModel([_text("member done")]))
    team = Team(
        members=[member],
        model=ScriptedModel(_probe_script()),
        tools=[_dependency_probe(seen)],
        dependencies={"ns": _namespace_dependency},
    )
    first = team.run("probe once")
    if mode == "async":
        continued = asyncio.run(team.acontinue_run(run_response=first, input="probe again"))
    else:

        async def _consume() -> Optional[TeamRunOutput]:
            output: Optional[TeamRunOutput] = None
            async for event in team.acontinue_run(
                run_response=first, input="probe again", stream=True, yield_run_output=True
            ):
                if isinstance(event, TeamRunOutput):
                    output = event
            return output

        continued = asyncio.run(_consume())

    assert continued is not None
    assert continued.run_id != first.run_id, "the team continuation did not fork a sibling run"
    assert len(seen) == 2
    for run_output, (context_run_id, dependency) in zip((first, continued), seen):
        expected = run_output.run_id
        assert context_run_id == expected
        assert dependency == f"ns::{expected}", f"team run {expected}: dependency resolved against {dependency}"


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


@pytest.mark.parametrize("mode", ["async", "async_stream"])
def test_agent_async_continue_retry_resolves_dependencies_against_the_executing_fork(mode):
    """A transient model failure re-enters the retry loop, which forks AGAIN — the first
    fork is abandoned. The dependency factories were already consumed against the
    abandoned fork, so without re-resolving from the unresolved values the run that
    actually completes executes with the abandoned fork's dependency."""
    seen: List[Tuple[Optional[str], Optional[str]]] = []
    agent = Agent(
        model=ScriptedModel(_retry_probe_script()),
        tools=[_dependency_probe(seen)],
        dependencies={"ns": _namespace_dependency},
        retries=1,
        delay_between_retries=0,
    )
    first = agent.run("probe once")
    if mode == "async":
        continued = asyncio.run(agent.acontinue_run(run_response=first, input="probe again"))
    else:

        async def _consume() -> Optional[RunOutput]:
            output: Optional[RunOutput] = None
            async for event in agent.acontinue_run(
                run_response=first, input="probe again", stream=True, yield_run_output=True
            ):
                if isinstance(event, RunOutput):
                    output = event
            return output

        continued = asyncio.run(_consume())

    assert continued is not None
    assert continued.run_id != first.run_id
    assert len(seen) == 2, f"expected one probe per completed model loop, got {seen}"
    context_run_id, dependency = seen[1]
    assert context_run_id == continued.run_id
    assert dependency == f"ns::{continued.run_id}", (
        f"the completing run {continued.run_id} executed with a dependency scoped to an abandoned fork: {dependency}"
    )


@pytest.mark.parametrize("mode", ["async", "async_stream"])
def test_team_async_continue_retry_resolves_dependencies_against_the_executing_fork(mode):
    """The team twin of the retry test above."""
    from agno.run.team import TeamRunOutput

    seen: List[Tuple[Optional[str], Optional[str]]] = []
    member = Agent(name="member", model=ScriptedModel([_text("member done")]))
    team = Team(
        members=[member],
        model=ScriptedModel(_retry_probe_script()),
        tools=[_dependency_probe(seen)],
        dependencies={"ns": _namespace_dependency},
        retries=1,
        delay_between_retries=0,
    )
    first = team.run("probe once")
    if mode == "async":
        continued = asyncio.run(team.acontinue_run(run_response=first, input="probe again"))
    else:

        async def _consume() -> Optional[TeamRunOutput]:
            output: Optional[TeamRunOutput] = None
            async for event in team.acontinue_run(
                run_response=first, input="probe again", stream=True, yield_run_output=True
            ):
                if isinstance(event, TeamRunOutput):
                    output = event
            return output

        continued = asyncio.run(_consume())

    assert continued is not None
    assert continued.run_id != first.run_id
    assert len(seen) == 2, f"expected one probe per completed model loop, got {seen}"
    context_run_id, dependency = seen[1]
    assert context_run_id == continued.run_id
    assert dependency == f"ns::{continued.run_id}", (
        f"the completing team run {continued.run_id} executed with a dependency scoped to "
        f"an abandoned fork: {dependency}"
    )


def test_team_rebind_cannot_blank_the_session_id():
    from agno.run.team import TeamRunOutput
    from agno.team._run import _bind_run_context_to_team_run

    member = Agent(name="member", model=ScriptedModel([_text("x")]))
    team = Team(members=[member], model=ScriptedModel([_text("x")]))
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
