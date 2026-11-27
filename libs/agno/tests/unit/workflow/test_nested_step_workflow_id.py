"""An agent or team knows its workflow while a step runs it, wherever the step sits, and only then.

An agent that does not know it runs in a workflow saves its own session under the workflow's
session id, and the workflow's session row is then stored as that agent's session. An agent that
still carried the workflow's id after the run would stop saving the sessions of its own runs.
"""

import asyncio
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

import pytest

from agno.agent import Agent
from agno.agent._session import saves_its_runs
from agno.db.base import SessionType
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.team.mode import TeamMode
from agno.workflow import Condition, Loop, Parallel, Router, Step, Steps, Workflow
from agno.workflow import step as step_module
from agno.workflow.step import running_as_workflow_step
from agno.workflow.types import HumanReview, StepOutput


def _agent(name: str, db: InMemoryDb, **kwargs) -> Agent:
    return Agent(id=name, name=name, db=db, **kwargs)


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Optional[str]]:
    """The workflow id each agent or team held when the workflow ran it, without calling a model."""
    seen: Dict[str, Optional[str]] = {}

    def output(self):
        seen[self.id] = self.workflow_id
        if isinstance(self, Team):
            return TeamRunOutput(run_id=f"{self.id}-run", content="done")
        return RunOutput(run_id=f"{self.id}-run", content="done")

    def run(self, *args, stream=False, **kwargs):
        if not stream:
            return output(self)

        def events():
            # Read while the stream is consumed: the agent saves at the end of its stream.
            yield output(self)

        return events()

    def arun(self, *args, stream=False, **kwargs):
        async def result():
            return output(self)

        async def events():
            yield output(self)

        return events() if stream else result()

    for owner in (Agent, Team):
        monkeypatch.setattr(owner, "run", run)
        monkeypatch.setattr(owner, "arun", arun)
    return seen


def _run(workflow: Workflow, mode: str, **kwargs):
    if mode == "run":
        return workflow.run(**kwargs)
    if mode == "run-stream":
        return list(workflow.run(stream=True, **kwargs))
    if mode == "arun":
        return asyncio.run(workflow.arun(**kwargs))

    async def consume():
        return [event async for event in workflow.arun(stream=True, **kwargs)]

    return asyncio.run(consume())


MODES = ["run", "run-stream", "arun", "arun-stream"]


def _workflow(db: InMemoryDb) -> Workflow:
    return Workflow(
        id="nested-workflow",
        db=db,
        steps=[
            Step(name="top", agent=_agent("top", db)),
            Loop(
                name="loop",
                max_iterations=1,
                steps=[
                    Parallel(
                        Step(name="parallel-step", agent=_agent("in-parallel", db)),
                        _agent("listed-in-parallel", db),
                        name="parallel",
                    ),
                    Step(name="loop-step", agent=_agent("in-loop", db)),
                    Condition(
                        name="condition",
                        evaluator=False,
                        steps=[Step(name="then", agent=_agent("in-condition", db))],
                        else_steps=[Step(name="else", agent=_agent("in-else", db))],
                    ),
                    Steps(name="steps", steps=[Step(name="steps-step", agent=_agent("in-steps", db))]),
                    Step(
                        name="team-step",
                        team=Team(id="team", name="team", members=[_agent("member", db)], db=db),
                    ),
                ],
            ),
            Router(
                name="router",
                selector=lambda step_input: "choice",
                choices=[Step(name="choice", agent=_agent("in-router", db))],
            ),
        ],
    )


RUN_BY_WORKFLOW = [
    "top",
    "in-parallel",
    "listed-in-parallel",
    "in-loop",
    "in-else",
    "in-steps",
    "team",
    "in-router",
]


@pytest.mark.parametrize("mode", MODES)
def test_nested_agents_and_teams_know_their_workflow_while_they_run(seen, mode):
    workflow = _workflow(InMemoryDb())

    _run(workflow, mode, input="hello", session_id="session")

    assert seen == {name: "nested-workflow" for name in RUN_BY_WORKFLOW}


@pytest.mark.parametrize("mode", MODES)
def test_an_agent_saves_its_own_runs_again_after_the_workflow(seen, mode):
    workflow = _workflow(InMemoryDb())
    loop_steps = workflow.steps[1].steps  # type: ignore[index, union-attr]
    nested = loop_steps[1].agent
    not_run = loop_steps[2].steps[0].agent
    team = loop_steps[4].team

    _run(workflow, mode, input="hello", session_id="session")

    # Run on its own after the workflow, each of these saves its own session.
    for agent in (workflow.steps[0].agent, nested, not_run, team.members[0]):  # type: ignore[index, union-attr]
        assert agent.workflow_id is None
        assert saves_its_runs(agent) is True
    assert team.workflow_id is None


@pytest.mark.parametrize("mode", MODES)
def test_a_step_returned_by_a_router_selector_knows_its_workflow(seen, mode):
    db = InMemoryDb()
    declared = Step(name="declared", agent=_agent("declared", db))
    # The selector hands back its own Step objects: the declared one, which a copy of the workflow
    # does not hold, and one that is not among the choices at all.
    built = Step(name="built", agent=_agent("built", db))
    workflow = Workflow(
        id="router-workflow",
        db=db,
        steps=[Router(name="router", selector=lambda step_input: [declared, built], choices=[declared])],
    )

    _run(workflow.deep_copy(), mode, input="hello", session_id="session")

    assert seen == {"declared": "router-workflow", "built": "router-workflow"}


@pytest.mark.parametrize("mode", ["run", "arun"])
def test_a_step_run_after_a_pause_on_a_new_workflow_knows_its_workflow(seen, mode):
    db = InMemoryDb()

    def build() -> Workflow:
        return Workflow(
            id="paused-workflow",
            db=db,
            steps=[
                Step(
                    name="gate",
                    executor=lambda step_input: StepOutput(content="passed"),
                    human_review=HumanReview(requires_confirmation=True),
                ),
                Loop(name="loop", max_iterations=1, steps=[Step(name="nested", agent=_agent("after-pause", db))]),
                Step(name="top", agent=_agent("top-after-pause", db)),
            ],
        )

    paused = _run(build(), mode, input="hello", session_id="session")
    assert paused.is_paused
    for requirement in paused.active_step_requirements:
        requirement.confirm()

    # AgentOS continues a run on a new copy of the workflow.
    if mode == "run":
        build().continue_run(paused)
    else:
        asyncio.run(build().acontinue_run(paused))

    assert seen == {"after-pause": "paused-workflow", "top-after-pause": "paused-workflow"}


def test_a_nested_workflow_keeps_its_own_agents(seen):
    db = InMemoryDb()
    inner = Workflow(
        id="inner-workflow", db=db, steps=[Loop(steps=[Step(name="inner-step", agent=_agent("inner", db))])]
    )
    outer = Workflow(
        id="outer-workflow",
        db=db,
        steps=[Loop(max_iterations=1, steps=[Step(name="nested", workflow=inner)])],
    )

    outer.run(input="hello", session_id="session")

    assert seen == {"inner": "inner-workflow"}


def test_the_mark_holds_until_the_last_step_running_the_agent_ends():
    db = InMemoryDb()
    team = Team(id="team", name="team", members=[_agent("member", db)], db=db)

    # The same team runs in two steps at once, as in two branches of a Parallel.
    first = running_as_workflow_step(team, "workflow")
    second = running_as_workflow_step(team, "workflow")
    first.__enter__()
    second.__enter__()
    first.__exit__(None, None, None)
    assert (team.workflow_id, team.members[0].workflow_id) == ("workflow", "workflow")  # type: ignore[union-attr]

    second.__exit__(None, None, None)
    assert (team.workflow_id, team.members[0].workflow_id) == (None, None)  # type: ignore[union-attr]


def test_a_step_agent_with_its_own_history_is_told_it_is_not_loaded(seen, monkeypatch: pytest.MonkeyPatch):
    warnings: List[str] = []
    monkeypatch.setattr(step_module, "log_warning", warnings.append)
    monkeypatch.setattr(step_module, "_HISTORY_WARNED", set())
    db = InMemoryDb()
    workflow = Workflow(
        id="history-workflow",
        db=db,
        steps=[
            Loop(
                name="loop",
                max_iterations=2,
                steps=[
                    Step(name="writer", agent=_agent("writer", db, add_history_to_context=True)),
                    Step(
                        name="reviewer",
                        agent=_agent("reviewer", db, add_history_to_context=True),
                        add_workflow_history=True,
                    ),
                    Step(name="plain", agent=_agent("plain", db)),
                ],
            )
        ],
    )

    workflow.run(input="hello", session_id="session")
    workflow.run(input="hello again", session_id="session")

    # Once for the writer. The reviewer gets the workflow's history, and the third agent asked for none.
    assert len(warnings) == 1
    assert "'writer'" in warnings[0] and "add_workflow_history" in warnings[0]


class _Model(Model):
    """Answers "ok" without a provider. Its stream is slow enough to stop in the middle."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self._response = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        for _ in range(5):
            await asyncio.sleep(0.02)
            yield self._response

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._response


def _stored(db: InMemoryDb, session_id: str) -> Tuple[Optional[str], List[Optional[str]]]:
    """The stored session's type, and for each of its runs the workflow, team or agent that owns it."""
    row = db._sessions.get(session_id) or {}
    owners = [run.get("workflow_id") or run.get("team_id") or run.get("agent_id") for run in row.get("runs") or []]
    return row.get("session_type"), owners


def _step_executor(kind: str, db: InMemoryDb, **kwargs) -> Dict[str, Any]:
    if kind == "agent":
        return {"agent": Agent(id="agent", name="agent", db=db, model=_Model(), **kwargs)}
    member = Agent(id="member", name="member", db=db, model=_Model())
    # A team in tasks mode streams through a second generator, which ends after the step does.
    mode = TeamMode.tasks if kind == "tasks team" else TeamMode.coordinate
    return {"team": Team(id="team", name="team", db=db, model=_Model(), members=[member], mode=mode, **kwargs)}


def _one_step_workflow(kind: str, db: InMemoryDb) -> Workflow:
    return Workflow(
        id="workflow",
        db=db,
        steps=[Loop(name="loop", max_iterations=1, steps=[Step(name="step", **_step_executor(kind, db))])],
    )


@pytest.mark.parametrize("mode", MODES)
def test_an_agent_run_on_its_own_after_the_workflow_is_stored(mode):
    db = InMemoryDb()
    workflow = _one_step_workflow("agent", db)
    agent = workflow.steps[0].steps[0].agent  # type: ignore[index, union-attr]

    _run(workflow, mode, input="hello", session_id="workflow-session")
    agent.run("a question", session_id="chat")
    agent.run("another", session_id="chat")

    assert _stored(db, "workflow-session") == ("workflow", ["workflow"])
    assert _stored(db, "chat") == ("agent", ["agent", "agent"])


@pytest.mark.parametrize("kind", ["agent", "team", "tasks team"])
@pytest.mark.parametrize("stopped_by", ["closing the stream", "cancelling the task"])
def test_a_step_stopped_in_the_middle_of_its_stream_saves_no_run_of_its_own(kind, stopped_by):
    """The agent or team saves a cancelled run on a task that outlives the step."""
    db = InMemoryDb()
    workflow = _one_step_workflow(kind, db)

    async def stop_in_the_middle():
        stream = workflow.arun(input="hello", session_id="workflow-session", stream=True, stream_events=True)
        if stopped_by == "closing the stream":
            # A client that disconnects: the stream is closed while the model is still answering.
            async for event in stream:
                if "RunContent" in type(event).__name__:
                    break
            await stream.aclose()
        else:

            async def consume():
                async for _ in stream:
                    pass

            task = asyncio.create_task(consume())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        # Let the cancelled run's own save finish.
        await asyncio.sleep(0.2)

    asyncio.run(stop_in_the_middle())

    assert _stored(db, "workflow-session") == ("workflow", ["workflow"])


def test_a_streamed_step_run_is_stored_as_completed():
    db = InMemoryDb()
    workflow = _one_step_workflow("agent", db)

    _run(workflow, "arun-stream", input="hello", session_id="workflow-session")

    session = db.get_session(session_id="workflow-session", session_type=SessionType.WORKFLOW)
    statuses = [run.status for run in session.runs[0].step_executor_runs]  # type: ignore[union-attr, index]
    assert statuses == [RunStatus.completed]


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_step_history_reads_the_executors_session_when_none_is_given(kind):
    db = InMemoryDb()
    step = Step(name="step", **_step_executor(kind, db, session_id="workflow-session"))
    workflow = Workflow(id="workflow", db=db, steps=[step])

    workflow.run(input="hello", session_id="workflow-session")

    given = step.get_chat_history(session_id="workflow-session")
    assert len(given) > 0
    assert len(asyncio.run(step.aget_chat_history())) == len(given)
