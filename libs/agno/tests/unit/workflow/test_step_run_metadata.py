"""A workflow step can set the metadata of its agent's or team's run.

A sandboxed coding engineer reads what to check out from that metadata, and works in a session of
its own per checkout.
"""

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.exceptions import ComponentRehydrationError
from agno.registry import Registry
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.sandbox import Repository
from agno.sandbox.docker import DockerSandbox
from agno.team import Team
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput
from tests.unit.team.test_external_agent_members import _delegate, _ScriptedModel


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "steps.db"))


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    """The options each agent or team was run with, without calling a model."""
    seen: List[Dict[str, Any]] = []

    def output(self) -> Any:
        cls = TeamRunOutput if isinstance(self, Team) else RunOutput
        return cls(run_id=f"{self.id}-run", content="done")

    def run(self, *args, **kwargs):
        seen.append({"id": self.id, **kwargs})
        if kwargs.get("stream"):
            return iter([output(self)])
        return output(self)

    def arun(self, *args, **kwargs):
        seen.append({"id": self.id, **kwargs})
        if kwargs.get("stream"):

            async def stream():
                yield output(self)

            return stream()

        async def result():
            return output(self)

        return result()

    for owner in (Agent, Team):
        monkeypatch.setattr(owner, "run", run)
        monkeypatch.setattr(owner, "arun", arun)
    return seen


def _drain(workflow: Workflow, mode: str, message: str = "https://github.com/acme/app/pull/7") -> None:
    if mode == "run":
        workflow.run(input=message)
    elif mode == "run_stream":
        list(workflow.run(input=message, stream=True))
    elif mode == "arun":
        asyncio.run(workflow.arun(input=message))
    else:

        async def drain():
            async for _ in workflow.arun(input=message, stream=True):
                pass

        asyncio.run(drain())


MODES = ["run", "run_stream", "arun", "arun_stream"]


def pull_request_of_the_input(step_input: StepInput) -> Dict[str, Any]:
    """The pull request the workflow was given, as the checkout for a coding engineer."""
    return {"repository": {"pull_request": int(str(step_input.input).rsplit("/", 1)[-1])}}


def branch_from_session_state(step_input: StepInput, run_context: RunContext) -> Optional[Dict[str, Any]]:
    branch = (run_context.session_state or {}).get("branch")
    return {"repository": {"branch": branch}} if branch else None


@pytest.mark.parametrize("mode", MODES)
def test_a_steps_run_metadata_reaches_its_agent(runs, mode):
    workflow = Workflow(
        id="wf",
        steps=[
            Step(name="plain", agent=Agent(id="plain")),
            Step(name="fixed", agent=Agent(id="fixed"), run_metadata={"repository": {"branch": "release"}}),
            Step(name="from-input", agent=Agent(id="from-input"), run_metadata=pull_request_of_the_input),
        ],
    )

    _drain(workflow, mode)

    by_id = {run["id"]: run for run in runs}
    assert "metadata" not in by_id["plain"]
    assert by_id["fixed"]["metadata"] == {"repository": {"branch": "release"}}
    assert by_id["from-input"]["metadata"] == {"repository": {"pull_request": 7}}


@pytest.mark.parametrize("mode", MODES)
def test_a_run_metadata_function_can_read_the_run_context_and_return_nothing(runs, mode):
    def set_branch(step_input: StepInput, run_context: RunContext) -> StepOutput:
        assert run_context.session_state is not None
        run_context.session_state["branch"] = "hotfix"
        return StepOutput(content="chosen")

    workflow = Workflow(
        id="wf",
        session_state={},
        steps=[
            Step(name="before", agent=Agent(id="before"), run_metadata=branch_from_session_state),
            Step(name="choose", executor=set_branch),
            Step(name="after", team=Team(id="after", members=[Agent(id="m")]), run_metadata=branch_from_session_state),
        ],
    )

    _drain(workflow, mode)

    by_id = {run["id"]: run for run in runs}
    # The function returned None before a branch was chosen: the run gets no metadata.
    assert "metadata" not in by_id["before"]
    # A team is given the metadata like an agent; it passes its run's metadata on to its members.
    assert by_id["after"]["metadata"] == {"repository": {"branch": "hotfix"}}


def test_run_metadata_that_is_not_a_dict_never_reaches_the_agent(runs):
    workflow = Workflow(id="wf", steps=[Step(name="bad", agent=Agent(id="bad"), run_metadata=lambda step_input: "x")])

    workflow.run(input="go")

    # The agent is never run with a value it was not meant to get.
    assert runs == []


def test_run_metadata_is_stored_with_the_step_and_loaded_again():
    registry = Registry(agents=[Agent(id="coder")], functions=[pull_request_of_the_input])
    fixed = Step(name="fixed", agent=Agent(id="coder"), run_metadata={"repository": {"branch": "release"}})
    function = Step(name="function", agent=Agent(id="coder"), run_metadata=pull_request_of_the_input)

    assert fixed.to_dict()["run_metadata"] == {"repository": {"branch": "release"}}
    assert "run_metadata_ref" not in fixed.to_dict()
    assert function.to_dict()["run_metadata_ref"] == "pull_request_of_the_input"
    assert "run_metadata" not in function.to_dict()
    assert "run_metadata" not in Step(name="plain", agent=Agent(id="coder")).to_dict()

    assert Step.from_dict(fixed.to_dict(), registry=registry).run_metadata == {"repository": {"branch": "release"}}
    assert Step.from_dict(function.to_dict(), registry=registry).run_metadata is pull_request_of_the_input

    # A function the registry does not hold: a strict load refuses, a lenient one keeps the name.
    empty = Registry(agents=[Agent(id="coder")])
    with pytest.raises(ComponentRehydrationError, match="pull_request_of_the_input"):
        Step.from_dict(function.to_dict(), registry=empty, strict=True)
    lenient = Step.from_dict(function.to_dict(), registry=empty, strict=False)
    assert lenient.to_dict()["run_metadata_ref"] == "pull_request_of_the_input"


# ---------------------------------------------------------------------------
# A sandboxed engineer: one session per checkout
# ---------------------------------------------------------------------------


@pytest.fixture
def engineer(db, monkeypatch: pytest.MonkeyPatch):
    """A sandboxed engineer whose sandbox turns are recorded and never started."""
    from agno.db.postgres import PostgresDb
    from agno.sandbox import _harness

    coder = ClaudeAgent(
        id="claude-1",
        # A sandboxed agent requires PostgreSQL. Nothing connects: its sandbox turns are stood in for below.
        db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:1/ai"),
        sandbox=DockerSandbox(image="fixture"),
        repository=Repository(url="https://github.com/acme/app", branch="main"),
    )
    turns: List[Dict[str, Any]] = []

    async def arun(agent, input, **kwargs):
        turns.append({"input": input, **kwargs})
        return RunOutput(run_id=kwargs["run_id"], agent_id=agent.id, content="reviewed", status=RunStatus.completed)

    async def astream(agent, input, **kwargs):
        yield await arun(agent, input, **kwargs)

    monkeypatch.setattr(_harness, "arun", arun)
    monkeypatch.setattr(_harness, "astream", astream)
    return coder, turns


def test_a_sandboxed_steps_options_name_a_session_per_checkout(engineer):
    coder, _ = engineer

    def session(metadata: Optional[Dict[str, Any]]) -> str:
        options = {"run_id": "r1", "session_id": "w1", **({"metadata": metadata} if metadata is not None else {})}
        return coder._sandboxed_member_kwargs(options, "w1", "r1", workflow_id="wf")["session_id"]

    assert session(None) == "w1:claude-1"
    assert session({"topic": "billing"}) == "w1:claude-1"
    assert session({"repository": {"pull_request": 7}}) == "w1:claude-1@pr-7"
    assert session({"repository": {"branch": "release"}}) == "w1:claude-1@branch-release"
    # A team member is keyed the same way.
    options = {"run_id": "r1", "session_id": "t1", "metadata": {"repository": {"pull_request": 7}}}
    assert coder._sandboxed_member_kwargs(options, "t1", "r1", team_id="team")["session_id"] == "t1:claude-1@pr-7"


@pytest.mark.parametrize("mode", ["run", "arun"])
def test_one_engineer_in_two_steps_checks_out_two_refs_in_two_sessions(db, engineer, mode):
    coder, turns = engineer
    workflow = Workflow(
        id="wf",
        db=db,
        steps=[
            Step(name="the pull request", agent=coder, run_metadata=pull_request_of_the_input),
            Step(name="the release branch", agent=coder, run_metadata={"repository": {"branch": "release"}}),
            Step(name="the pull request again", agent=coder, run_metadata=pull_request_of_the_input),
        ],
    )

    if mode == "run":
        output = workflow.run(input="https://github.com/acme/app/pull/7", session_id="w1")
    else:
        output = asyncio.run(workflow.arun(input="https://github.com/acme/app/pull/7", session_id="w1"))

    assert output.status == RunStatus.completed
    assert [(turn["session_id"], turn["metadata"]) for turn in turns] == [
        ("w1:claude-1@pr-7", {"repository": {"pull_request": 7}}),
        ("w1:claude-1@branch-release", {"repository": {"branch": "release"}}),
        # The same checkout again: the same session, so the same files and conversation.
        ("w1:claude-1@pr-7", {"repository": {"pull_request": 7}}),
    ]


def test_a_team_run_for_a_pull_request_sends_its_engineer_member_to_that_checkout(db, engineer):
    """A team passes its run's metadata to each member call, so the team's run says what the engineer checks out."""
    coder, turns = engineer
    script = [_delegate("claude-1", "Review it", "c1"), ("content", "done")]
    team = Team(id="team", name="Team", members=[coder], model=_ScriptedModel(script), db=db)

    output = team.run("Review the pull request", session_id="t1", metadata={"repository": {"pull_request": 7}})

    assert output.status == RunStatus.completed
    [turn] = turns
    assert turn["session_id"] == "t1:claude-1@pr-7"
    assert turn["metadata"] == {"repository": {"pull_request": 7}}
