"""Workflow run-output helpers must honor an explicitly requested session."""

import pytest

from agno.db.in_memory import InMemoryDb
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession
from agno.workflow.workflow import Workflow


def _seed_session(db: InMemoryDb, session_id: str, content: str) -> None:
    session = WorkflowSession(session_id=session_id, workflow_id="workflow-1")
    session.upsert_run(
        WorkflowRunOutput(
            run_id="shared-run-id",
            session_id=session_id,
            workflow_id="workflow-1",
            content=content,
            status=RunStatus.completed,
        )
    )
    db.upsert_session(session)


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.asyncio
async def test_run_output_helpers_do_not_return_cached_other_session(async_mode: bool):
    db = InMemoryDb()
    _seed_session(db, "session-a", "from-a")
    _seed_session(db, "session-b", "from-b")
    workflow = Workflow(id="workflow-1", db=db, cache_session=True, telemetry=False)

    if async_mode:
        await workflow.aread_or_create_session(session_id="session-a")
        run_output = await workflow.aget_run_output("shared-run-id", session_id="session-b")
        last_run_output = await workflow.aget_last_run_output(session_id="session-b")
    else:
        workflow.read_or_create_session(session_id="session-a")
        run_output = workflow.get_run_output("shared-run-id", session_id="session-b")
        last_run_output = workflow.get_last_run_output(session_id="session-b")

    assert run_output is not None and run_output.content == "from-b"
    assert last_run_output is not None and last_run_output.content == "from-b"
