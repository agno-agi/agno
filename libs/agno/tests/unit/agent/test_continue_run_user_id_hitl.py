"""Regression: continue_run must restore RunContext.user_id after HITL confirmation.

Issue #9288 — when resuming via continue_run(run_response=...) without an explicit
user_id=, Agno previously only fell back to agent.user_id and dropped the identity
stored on the paused RunOutput. Workflow executor HITL also called continue_run
without forwarding user_id, so confirmed tools saw RunContext.user_id is None.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, Optional

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.base import RunContext
from agno.run.workflow import WorkflowRunOutput
from agno.tools import tool
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow, _resolve_continue_user_id


CAPTURE: Dict[str, Any] = {}


class ToolCallThenDoneModel(Model):
    """First call requests a tool; second call returns plain content."""

    def __init__(self) -> None:
        super().__init__(id="repro-model", name="repro-model", provider="test")
        self.calls = 0

    def __deepcopy__(self, memo: dict[int, Any]) -> "ToolCallThenDoneModel":
        clone = type(self)()
        clone.calls = self.calls
        return clone

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "tc-probe-1",
                        "type": "function",
                        "function": {"name": "probe", "arguments": "{}"},
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content="done", response_usage=MessageMetrics())

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


@tool(requires_confirmation=True)
def probe(run_context: Optional[RunContext] = None) -> str:
    CAPTURE["tool_user_id"] = getattr(run_context, "user_id", None) if run_context else None
    return f"probe_user={CAPTURE['tool_user_id']!r}"


def test_resolve_continue_user_id_prefers_paused_then_workflow() -> None:
    paused = type("Paused", (), {"user_id": "from-paused"})()
    workflow = type("WorkflowRun", (), {"user_id": "from-workflow"})()
    assert _resolve_continue_user_id(paused, workflow) == "from-paused"

    paused_missing = type("Paused", (), {"user_id": None})()
    assert _resolve_continue_user_id(paused_missing, workflow) == "from-workflow"


def test_agent_continue_run_restores_user_id_after_confirmation(tmp_path: Path) -> None:
    CAPTURE.clear()
    agent = Agent(
        name="ProbeAgent",
        model=ToolCallThenDoneModel(),
        tools=[probe],
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        telemetry=False,
    )

    paused = agent.run("go", user_id="user-from-run")
    assert paused.is_paused
    assert paused.user_id == "user-from-run"

    for req in paused.active_requirements or []:
        req.confirm()

    # Intentionally omit user_id= — identity must come from paused.run_response.
    continued = agent.continue_run(run_response=paused)
    assert not continued.is_paused
    assert CAPTURE.get("tool_user_id") == "user-from-run"


@pytest.mark.asyncio
async def test_agent_acontinue_run_restores_user_id_after_confirmation(tmp_path: Path) -> None:
    CAPTURE.clear()
    agent = Agent(
        name="ProbeAgentAsync",
        model=ToolCallThenDoneModel(),
        tools=[probe],
        db=SqliteDb(db_file=str(tmp_path / "agent_async.db")),
        telemetry=False,
    )

    paused = await agent.arun("go", user_id="user-from-arun")
    assert paused.is_paused
    assert paused.user_id == "user-from-arun"

    for req in paused.active_requirements or []:
        req.confirm()

    continued = await agent.acontinue_run(run_response=paused)
    assert not continued.is_paused
    assert CAPTURE.get("tool_user_id") == "user-from-arun"


def test_workflow_executor_hitl_continue_preserves_user_id(tmp_path: Path) -> None:
    CAPTURE.clear()
    db = SqliteDb(db_file=str(tmp_path / "workflow.db"))
    agent = Agent(
        name="ProbeAgent2",
        model=ToolCallThenDoneModel(),
        tools=[probe],
        db=db,
        telemetry=False,
    )
    wf = Workflow(
        name="ProbeWorkflow",
        db=db,
        steps=[Step(name="probe_step", agent=agent)],
        telemetry=False,
    )

    paused_wf = wf.run(input="go", user_id="user-from-workflow")
    assert paused_wf.is_paused
    assert paused_wf.user_id == "user-from-workflow"
    assert paused_wf.step_requirements

    req = paused_wf.step_requirements[-1]
    for executor_req in req.executor_requirements or []:
        if isinstance(executor_req, dict):
            executor_req["confirmation"] = True
            te = executor_req.get("tool_execution")
            if isinstance(te, dict):
                te["confirmed"] = True
        else:
            executor_req.confirm()

    continued = wf.continue_run(paused_wf)
    assert not continued.is_paused
    assert CAPTURE.get("tool_user_id") == "user-from-workflow"


def test_workflow_continue_forwards_user_id_when_paused_executor_lacks_it() -> None:
    """Even if nested RunOutput.user_id is missing, workflow identity is forwarded."""
    paused = type("Paused", (), {"user_id": None})()
    workflow_run = WorkflowRunOutput(
        run_id="wf-run",
        workflow_id="wf",
        workflow_name="wf",
        session_id="s1",
        user_id="wf-user",
    )
    assert _resolve_continue_user_id(paused, workflow_run) == "wf-user"
