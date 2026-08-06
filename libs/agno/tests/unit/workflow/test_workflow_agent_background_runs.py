"""Backfill for PR #9258: background WorkflowAgent turns persist exactly ONE
run, carrying the 202'd run id (the id-reuse contract that replaced the 9079
safety net), and cancellation still lands a run row despite the removed
pre-persist."""

import asyncio

import pytest

from agno.exceptions import RunCancelledException
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.workflow.workflow import Workflow


def make_workflow_agent_workflow(monkeypatch, executed: dict, mode: str = "persist_same_id"):
    """Workflow in workflow-agent mode with the agent execution stubbed.

    The stub mimics #9258's contract: it persists the REAL run under the run id
    it receives via run_context (no second id), or simulates legacy divergence
    when mode='mint_new_id'."""
    from agno.agent import Agent

    wf = Workflow(id="wfa", name="wfa", db=None, agent=Agent(id="inner"))

    # Session plumbing stubs: keep everything in-memory
    sessions: dict = {}

    class FakeSession:
        def __init__(self, session_id):
            self.session_id = session_id
            self.user_id = None  # v3 helpers read session.user_id
            self.runs = []

        def upsert_run(self, run=None, **kw):
            run = run or kw.get("run")
            self.runs = [r for r in self.runs if r.run_id != run.run_id] + [run]

        def get_run(self, run_id):
            return next((r for r in self.runs if r.run_id == run_id), None)

    async def _aload_or_create_session(session_id=None, user_id=None, session_state=None):
        sessions.setdefault(session_id, FakeSession(session_id))
        return sessions[session_id], (session_state or {})

    async def asave_session(session=None, **kw):
        pass

    monkeypatch.setattr(wf, "_aload_or_create_session", _aload_or_create_session)
    monkeypatch.setattr(wf, "asave_session", asave_session)
    monkeypatch.setattr(wf, "_has_async_db", lambda: True)
    monkeypatch.setattr(wf, "initialize_workflow", lambda: None)
    monkeypatch.setattr(wf, "_initialize_session", lambda session_id=None, user_id=None: (session_id or "s1", user_id))
    monkeypatch.setattr(wf, "_prepare_steps", lambda: None)
    monkeypatch.setattr(wf, "update_agents_and_teams_session_info", lambda: None)

    async def fake_execute_workflow_agent(user_input=None, execution_input=None, run_context=None, **kwargs):
        executed["run_context_run_id"] = run_context.run_id if run_context else None
        run_id = run_context.run_id if mode == "persist_same_id" else "divergent-id"
        session, _ = await _aload_or_create_session(session_id="s1")
        real_run = WorkflowRunOutput(
            run_id=run_id, workflow_id=wf.id, session_id="s1", status=RunStatus.completed, content="answer"
        )
        session.upsert_run(run=real_run)
        return real_run

    monkeypatch.setattr(wf, "_aexecute_workflow_agent", fake_execute_workflow_agent)
    return wf, sessions


@pytest.mark.asyncio
async def test_background_workflow_agent_persists_exactly_one_run(monkeypatch):
    executed: dict = {}
    wf, sessions = make_workflow_agent_workflow(monkeypatch, executed)

    out = await wf.arun(input="q", session_id="s1", background=True)
    accepted_id = out.run_id

    for _ in range(100):
        await asyncio.sleep(0.02)
        session = sessions.get("s1")
        if session and session.runs and session.runs[-1].status == RunStatus.completed:
            break

    session = sessions["s1"]
    assert len(session.runs) == 1, f"expected exactly one run, got {[r.run_id for r in session.runs]}"
    assert session.runs[0].run_id == accepted_id, "the executed run must carry the 202'd run id"
    assert executed["run_context_run_id"] == accepted_id, "inner execution must receive the caller's run id"


@pytest.mark.asyncio
async def test_background_workflow_agent_cancel_lands_a_run_row(monkeypatch):
    """With no pre-persisted placeholder, a cancel while waiting for a slot
    must still create a CANCELLED row for the 202'd id."""
    executed: dict = {}
    wf, sessions = make_workflow_agent_workflow(monkeypatch, executed)

    async def cancelled_execute(**kwargs):
        raise RunCancelledException("cancelled")

    monkeypatch.setattr(wf, "_aexecute_workflow_agent", cancelled_execute)

    out = await wf.arun(input="q", session_id="s1", background=True)

    for _ in range(100):
        await asyncio.sleep(0.02)
        session = sessions.get("s1")
        if session and session.runs:
            break

    session = sessions.get("s1")
    assert session is not None and session.runs, "cancel must land a run row even without a pre-persist"
    row = session.get_run(out.run_id)
    assert row is not None, "the cancelled row must carry the 202'd run id"
    assert row.status == RunStatus.cancelled


@pytest.mark.asyncio
async def test_background_workflow_agent_run_visible_while_executing(monkeypatch):
    """The 202'd run id must be poll-visible from acceptance,
    not only after execution writes. The skip removed with the 9079 safety net
    made non-durable WorkflowAgent background runs fully invisible while
    queued/executing - polls 404ed and tenant-scoped cancel had nothing to
    verify ownership against. The restored placeholder is reconciled by
    id-reuse (this file's exactly-one-run test pins that no duplicate comes
    back)."""
    executed: dict = {}
    wf, sessions = make_workflow_agent_workflow(monkeypatch, executed)

    release = asyncio.Event()

    async def hanging_then_real_execute(user_input=None, execution_input=None, run_context=None, **kwargs):
        executed["run_context_run_id"] = run_context.run_id if run_context else None
        await release.wait()
        session, _ = await wf._aload_or_create_session(session_id="s1")
        real_run = WorkflowRunOutput(
            run_id=run_context.run_id,
            workflow_id=wf.id,
            session_id="s1",
            status=RunStatus.completed,
            content="answer",
        )
        session.upsert_run(run=real_run)
        return real_run

    monkeypatch.setattr(wf, "_aexecute_workflow_agent", hanging_then_real_execute)

    out = await wf.arun(input="q", session_id="s1", background=True)
    accepted_id = out.run_id

    # While execution is in flight, the accepted run must already be a row
    for _ in range(100):
        await asyncio.sleep(0.01)
        session = sessions.get("s1")
        if session is not None and session.get_run(accepted_id) is not None:
            break
    session = sessions.get("s1")
    assert session is not None and session.get_run(accepted_id) is not None, (
        "the 202'd run id must be visible to pollers before execution writes anything"
    )
    placeholder = session.get_run(accepted_id)
    assert placeholder.status == RunStatus.pending

    # Release the leg: the real run must RECONCILE the placeholder, not join it
    release.set()
    for _ in range(100):
        await asyncio.sleep(0.01)
        row = sessions["s1"].get_run(accepted_id)
        if row is not None and row.status == RunStatus.completed:
            break
    assert len(sessions["s1"].runs) == 1, (
        f"expected the placeholder to be replaced, got {[r.run_id for r in sessions['s1'].runs]}"
    )
    assert sessions["s1"].runs[0].content == "answer"
