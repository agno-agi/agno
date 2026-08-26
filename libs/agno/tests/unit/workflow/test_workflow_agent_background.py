"""9258 backfill: background WorkflowAgent turns persist exactly ONE run
carrying the 202'd run id (the empty outer "0 of N steps" ghost must not
return), and cancel still lands a row with no pre-persisted placeholder.
"""

import asyncio
from typing import Optional

import pytest

from agno.db.in_memory import InMemoryDb
from agno.run.base import RunStatus
from agno.workflow.workflow import Workflow


def make_workflow():
    wf = Workflow(id="wfa-1", name="wfa", db=InMemoryDb(), steps=[])
    wf.agent = object()  # WorkflowAgent marker: routes _arun_background down the agent branch
    return wf


class TestWorkflowAgentBackgroundSingleRun:
    @pytest.mark.asyncio
    async def test_one_run_per_turn_with_the_202_id(self):
        wf = make_workflow()
        observed: dict = {}

        async def fake_execute(user_input=None, execution_input=None, run_context=None, stream=False, **kw):
            observed["run_id"] = run_context.run_id
            # The real path persists the run under the caller's id (9258),
            # pairing the session-row save with a per-run write
            from agno.run.workflow import WorkflowRunOutput

            session, _ = await wf._aload_or_create_session(
                session_id=run_context.session_id, user_id=None, session_state=None
            )
            run = WorkflowRunOutput(
                run_id=run_context.run_id,
                session_id=run_context.session_id,
                workflow_id=wf.id,
                status=RunStatus.completed,
                content="done",
            )
            session.upsert_run(run=run)
            await wf._apersist_session_and_run(session=session, run=run)
            from types import SimpleNamespace

            return SimpleNamespace(run_id=run_context.run_id, status=RunStatus.completed)

        wf._aexecute_workflow_agent = fake_execute  # type: ignore[method-assign]

        out = await wf.arun(input="hello", background=True, session_id="wfa-s1")
        for _ in range(50):
            await asyncio.sleep(0.05)
            if observed.get("run_id"):
                break

        assert observed["run_id"] == out.run_id, "execution must reuse the 202'd run id"
        session = await wf.aget_session(session_id="wfa-s1")
        runs = session.runs or []
        assert len(runs) == 1, f"exactly one run per turn, got {len(runs)}"
        assert runs[0].run_id == out.run_id
        assert runs[0].status == RunStatus.completed

    @pytest.mark.asyncio
    async def test_cancel_lands_a_row_without_preperisted_placeholder(self):
        """With no pre-persist, the RunCancelledException handler's upsert must
        CREATE the cancelled row."""
        from agno.exceptions import RunCancelledException

        wf = make_workflow()

        async def fake_execute(user_input=None, execution_input=None, run_context=None, stream=False, **kw):
            raise RunCancelledException()

        wf._aexecute_workflow_agent = fake_execute  # type: ignore[method-assign]

        out = await wf.arun(input="hello", background=True, session_id="wfa-s2")
        row_status: Optional[RunStatus] = None
        for _ in range(50):
            await asyncio.sleep(0.05)
            session = await wf.aget_session(session_id="wfa-s2")
            if session and session.runs:
                row_status = session.runs[-1].status
                break

        assert row_status == RunStatus.cancelled, f"cancel must land a row, got {row_status}"
        assert session.runs[-1].run_id == out.run_id
