"""Tests that a workflow step hands its agent/team executor the run-scoped owner.

``Workflow.user_id`` is only the instance-level default — the per-run owner lives on the
RunContext, and a Team forwards the ``user_id`` it was called with down to its members.
"""

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from agno.agent import Agent
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


@pytest.fixture
def team():
    return Team(name="Test Team", members=[Agent(name="Test Agent")])


def _team_output() -> TeamRunOutput:
    return TeamRunOutput(run_id="team-run-id", content="done")


def _spy_team(captured: List[Optional[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace Team.run/arun so the step's dispatch is observed without a model."""

    def spy_run(self_team, *args, **kwargs):
        captured.append(kwargs.get("user_id"))
        if kwargs.get("stream"):
            return iter([_team_output()])
        return _team_output()

    def spy_arun(self_team, *args, **kwargs):
        captured.append(kwargs.get("user_id"))
        if kwargs.get("stream"):

            async def stream_output():
                yield _team_output()

            return stream_output()

        async def output():
            return _team_output()

        return output()

    monkeypatch.setattr(Team, "run", spy_run)
    monkeypatch.setattr(Team, "arun", spy_arun)


def _drain(workflow: Workflow, mode: str, run_kwargs: Dict[str, Any]) -> None:
    if mode == "run":
        workflow.run(input="hello", **run_kwargs)
    elif mode == "run_stream":
        list(workflow.run(input="hello", stream=True, **run_kwargs))
    elif mode == "arun":
        asyncio.run(workflow.arun(input="hello", **run_kwargs))
    else:

        async def consume():
            async for _ in workflow.arun(input="hello", stream=True, **run_kwargs):
                pass

        asyncio.run(consume())


ALL_MODES = ["run", "run_stream", "arun", "arun_stream"]


class TestStepExecutorOwner:
    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_run_owner_reaches_team_executor(self, team, monkeypatch, mode):
        """The owner passed to workflow.run() reaches the team executor."""
        captured: List[Optional[str]] = []
        _spy_team(captured, monkeypatch)

        workflow = Workflow(name="Owner Test", steps=[Step(name="step1", team=team)])
        _drain(workflow, mode, {"user_id": "alice"})

        assert captured == ["alice"]

    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_run_owner_wins_over_workflow_default(self, team, monkeypatch, mode):
        """A per-run owner beats the workflow's instance-level default."""
        captured: List[Optional[str]] = []
        _spy_team(captured, monkeypatch)

        workflow = Workflow(name="Owner Test", user_id="carol", steps=[Step(name="step1", team=team)])
        _drain(workflow, mode, {"user_id": "alice"})

        assert captured == ["alice"]

    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_workflow_default_owner_used_when_run_has_none(self, team, monkeypatch, mode):
        """With no per-run owner, the workflow's default still applies."""
        captured: List[Optional[str]] = []
        _spy_team(captured, monkeypatch)

        workflow = Workflow(name="Owner Test", user_id="carol", steps=[Step(name="step1", team=team)])
        _drain(workflow, mode, {})

        assert captured == ["carol"]

    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_no_owner_stays_unscoped(self, team, monkeypatch, mode):
        """With no owner anywhere, the executor is called unscoped."""
        captured: List[Optional[str]] = []
        _spy_team(captured, monkeypatch)

        workflow = Workflow(name="Owner Test", steps=[Step(name="step1", team=team)])
        _drain(workflow, mode, {})

        assert captured == [None]
