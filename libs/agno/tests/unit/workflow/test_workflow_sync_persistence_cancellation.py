import asyncio
from contextvars import ContextVar
from threading import Event
from unittest.mock import Mock

import pytest

from agno.session.workflow import WorkflowSession
from agno.workflow.workflow import Workflow


def test_asave_session_settles_sync_persistence_before_cancellation(monkeypatch):
    entered = Event()
    release = Event()
    completed = Event()
    marker: ContextVar[str] = ContextVar("marker", default="missing")
    observed_context: list[str] = []

    workflow = Workflow(id="sync-persistence", db=Mock(), session_id="session-1")
    session = WorkflowSession(
        session_id="session-1",
        workflow_id="sync-persistence",
        session_data={},
    )

    monkeypatch.setattr(workflow, "_has_async_db", lambda: False)

    def blocking_upsert(*, session: WorkflowSession) -> WorkflowSession:
        observed_context.append(marker.get())
        entered.set()
        release.wait(timeout=2)
        completed.set()
        return session

    monkeypatch.setattr(workflow, "_upsert_session", blocking_upsert)

    async def invoke() -> None:
        marker.set("request-context")
        task = asyncio.create_task(workflow.asave_session(session))
        while not entered.is_set():
            await asyncio.sleep(0.01)

        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(invoke())

    assert completed.is_set()
    assert observed_context == ["request-context"]
