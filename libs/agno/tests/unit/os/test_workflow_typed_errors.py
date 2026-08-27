"""Workflow inline endpoints map typed errors like the agents endpoints.

The non-stream inline continue caught only InputCheckError and blanket-500ed
everything else: a race-losing continue (RunNotFoundError,
RunNotContinuableError, or the core's not-paused ValueError slipping past
the pre-check) surfaced as 500 "Error continuing workflow run: ..." where
agents answer 404/409/400. The inline submit's blanket except additionally
swallowed HTTPException itself and echoed raw internals in the detail.
"""

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.exceptions import RunNotContinuableError, RunNotFoundError
from agno.os import AgentOS
from agno.workflow import Workflow


@pytest.fixture()
def harness(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    workflow = Workflow(id="qa-wf", name="QA Workflow", db=db, steps=[])
    app = AgentOS(workflows=[workflow], telemetry=False).get_app()
    client = TestClient(app, raise_server_exceptions=False)

    sessions_table = db._get_table(table_type="sessions", create_table_if_not_found=True)
    runs_table = db._get_table(table_type="runs", create_table_if_not_found=True)
    with db.Session() as sess, sess.begin():
        sess.execute(
            sessions_table.insert().values(session_id="s-wf", session_type="workflow", created_at=int(time.time()))
        )
        sess.execute(
            runs_table.insert().values(
                run_id="r-wf-paused",
                session_id="s-wf",
                run_type="workflow",
                workflow_id="qa-wf",
                status="PAUSED",
                run_index=0,
                run_data=json.dumps(
                    {"run_id": "r-wf-paused", "session_id": "s-wf", "workflow_id": "qa-wf", "status": "PAUSED"}
                ),
                created_at=int(time.time()),
            )
        )
    return SimpleNamespace(client=client, db=db)


class TestContinueTypedErrorMapping:
    @pytest.mark.parametrize(
        "raised,expected_status",
        [
            (RunNotFoundError("run r-wf-paused not found"), 404),
            (RunNotContinuableError("run r-wf-paused is not continuable"), 409),
            (ValueError("Cannot continue a workflow run that is not paused"), 400),
        ],
    )
    def test_race_losing_continue_answers_typed(self, harness, monkeypatch, raised, expected_status):
        """The pre-check passes (the seeded run is PAUSED); the dispatch then
        loses the race and raises - the answer must be the same status the
        pre-check would have given, never a blanket 500."""

        async def racing_continue(self, **kwargs):
            raise raised

        monkeypatch.setattr(Workflow, "acontinue_run", racing_continue)
        resp = harness.client.post(
            "/workflows/qa-wf/runs/r-wf-paused/continue",
            data={"session_id": "s-wf", "stream": "false", "background": "false"},
        )
        assert resp.status_code == expected_status, f"expected {expected_status}, got {resp.status_code}: {resp.json()}"


class TestSubmitBlanket500Removed:
    def test_http_exception_is_not_flattened_to_500(self, harness, monkeypatch):
        """The old blanket except Exception caught HTTPException itself,
        flattening any typed 4xx raised inside the dispatch into a 500
        "Error running workflow: ..." - agents let it propagate."""
        from fastapi import HTTPException

        async def refusing_arun(self, **kwargs):
            raise HTTPException(status_code=429, detail="model rate limited")

        monkeypatch.setattr(Workflow, "arun", refusing_arun)
        resp = harness.client.post(
            "/workflows/qa-wf/runs",
            data={"message": "hi", "stream": "false", "background": "false"},
        )
        assert resp.status_code == 429, f"typed HTTPException must propagate, got {resp.status_code}: {resp.text}"
        assert resp.json()["detail"] == "model rate limited"


class TestPendingWordingInPausedGate:
    def test_queued_pending_run_gets_specific_wording(self, harness):
        """The workflow continue status map had no pending entry: a
        queued-PENDING run answered the generic not-paused wording while
        agents say "run is already pending"."""
        runs_table = harness.db._get_table(table_type="runs", create_table_if_not_found=True)
        with harness.db.Session() as sess, sess.begin():
            sess.execute(
                runs_table.insert().values(
                    run_id="r-wf-pending",
                    session_id="s-wf",
                    run_type="workflow",
                    workflow_id="qa-wf",
                    status="PENDING",
                    run_index=1,
                    run_data=json.dumps(
                        {"run_id": "r-wf-pending", "session_id": "s-wf", "workflow_id": "qa-wf", "status": "PENDING"}
                    ),
                    created_at=int(time.time()),
                )
            )
        resp = harness.client.post(
            "/workflows/qa-wf/runs/r-wf-pending/continue",
            data={"session_id": "s-wf", "stream": "false", "background": "false"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "run is already pending", f"got {resp.json()['detail']!r}"
