from types import MethodType

import pytest

from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.workflow import WorkflowSession
from agno.workflow import Step, Workflow


@pytest.mark.asyncio
async def test_workflow_async_stream_closes_executor_stream_before_session_save(monkeypatch: pytest.MonkeyPatch):
    order: list[str] = []
    agent = Agent(id="worker", name="Worker")

    async def fake_arun(self, **kwargs):
        try:
            yield RunOutput(
                run_id=kwargs["run_id"],
                session_id=kwargs["session_id"],
                content="done",
                status=RunStatus.completed,
            )
        finally:
            order.append("executor_stream_closed")

    agent.arun = MethodType(fake_arun, agent)  # type: ignore[method-assign]

    workflow = Workflow(
        id="workflow",
        name="Workflow",
        session_id="session",
        steps=[Step(name="agent-step", agent=agent)],
        telemetry=False,
    )
    session = WorkflowSession(
        session_id="session",
        workflow_id="workflow",
        workflow_name="Workflow",
        session_data={},
    )

    async def fake_load_or_create_session(*args, **kwargs):
        return session, {}

    async def fake_save_session(session):
        order.append("session_saved")

    monkeypatch.setattr(workflow, "_has_async_db", lambda: True)
    monkeypatch.setattr(workflow, "_aload_or_create_session", fake_load_or_create_session)
    monkeypatch.setattr(workflow, "asave_session", fake_save_session)

    stream = workflow.arun("run", stream=True, stream_events=True)
    events = [event async for event in stream]

    assert events[-1].event == "WorkflowCompleted"
    assert order == ["executor_stream_closed", "session_saved"]
