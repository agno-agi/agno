"""An agent or team nested in a Loop, Parallel, Condition, Router or Steps knows its workflow.

An agent that does not know it runs in a workflow saves its own session under the workflow's
session id, and the workflow's session row is then stored as that agent's session.
"""

import asyncio
from typing import Dict, Optional

import pytest

from agno.agent import Agent
from agno.agent._session import saves_its_runs
from agno.db.in_memory import InMemoryDb
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.workflow import Condition, Loop, Parallel, Router, Step, Steps, Workflow


def _agent(name: str, db: InMemoryDb) -> Agent:
    return Agent(id=name, name=name, db=db)


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Optional[str]]:
    """The workflow id each agent or team held when the workflow ran it, without calling a model."""
    seen: Dict[str, Optional[str]] = {}

    def run(self, *args, **kwargs):
        seen[self.id] = self.workflow_id
        if isinstance(self, Team):
            return TeamRunOutput(run_id=f"{self.id}-run", content="done")
        return RunOutput(run_id=f"{self.id}-run", content="done")

    async def arun(self, *args, **kwargs):
        return run(self, *args, **kwargs)

    for owner in (Agent, Team):
        monkeypatch.setattr(owner, "run", run)
        monkeypatch.setattr(owner, "arun", arun)
    return seen


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


@pytest.mark.parametrize("mode", ["run", "arun"])
def test_nested_agents_and_teams_know_their_workflow(seen, mode):
    workflow = _workflow(InMemoryDb())

    if mode == "run":
        workflow.run(input="hello", session_id="session")
    else:
        asyncio.run(workflow.arun(input="hello", session_id="session"))

    assert seen == {name: "nested-workflow" for name in RUN_BY_WORKFLOW}


def test_nested_agents_do_not_save_a_session_of_their_own():
    db = InMemoryDb()
    workflow = _workflow(db)
    nested = workflow.steps[1].steps[1].agent  # type: ignore[index, union-attr]
    not_run = workflow.steps[1].steps[2].steps[0].agent  # type: ignore[index, union-attr]
    member = workflow.steps[1].steps[4].team.members[0]  # type: ignore[index, union-attr]
    assert saves_its_runs(nested) is True

    workflow.update_agents_and_teams_session_info()

    # The workflow stores these runs with its own run, in its own session.
    assert saves_its_runs(nested) is False
    assert saves_its_runs(not_run) is False
    assert member.workflow_id == "nested-workflow"


def test_a_nested_workflow_keeps_its_own_agents():
    db = InMemoryDb()
    inner_agent = _agent("inner", db)
    inner = Workflow(id="inner-workflow", db=db, steps=[Loop(steps=[Step(name="inner-step", agent=inner_agent)])])
    outer = Workflow(id="outer-workflow", db=db, steps=[Loop(steps=[inner, Step(name="nested", workflow=inner)])])

    outer.update_agents_and_teams_session_info()

    assert inner_agent.workflow_id is None
