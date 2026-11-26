"""GET /eval-runs?status= filters suite runs by their summary status on SQLite, in-memory and JSON dbs."""

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.json import JsonDb
from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS


@pytest.fixture(params=["sqlite", "in_memory", "json"])
def db(request, tmp_path):
    if request.param == "sqlite":
        return SqliteDb(db_file=str(tmp_path / "status_filter.db"))
    if request.param == "in_memory":
        return InMemoryDb()
    return JsonDb(db_path=str(tmp_path / "status_filter_json"))


def _suite(db, run_id, status):
    db.create_eval_run(
        EvalRunRecord(
            run_id=run_id,
            eval_type=EvalType.SUITE,
            agent_id="assistant",
            eval_data={
                "summary": {
                    "total": 1,
                    "passed": int(status == "PASS"),
                    "failed": int(status == "FAIL"),
                    "status": status,
                },
                "cases": [],
            },
            eval_input={},
        )
    )


def _accuracy(db, run_id):
    db.create_eval_run(
        EvalRunRecord(run_id=run_id, eval_type=EvalType.ACCURACY, eval_data={"eval_status": "PASSED"}, eval_input={})
    )


def test_db_filters_suite_runs_by_status(db):
    _suite(db, "s-pass", "PASS")
    _suite(db, "s-fail", "FAIL")
    _accuracy(db, "a-1")

    rows, total = db.get_eval_runs(status="FAIL", deserialize=False)
    assert [row["run_id"] for row in rows] == ["s-fail"]
    assert total == 1

    rows, total = db.get_eval_runs(status="PASS", deserialize=False)
    assert [row["run_id"] for row in rows] == ["s-pass"]
    assert total == 1

    # No status: every run, including the accuracy one that has no summary.
    _, total = db.get_eval_runs(deserialize=False)
    assert total == 3


def test_route_passes_status_through():
    db = InMemoryDb()
    _suite(db, "s-pass", "PASS")
    _suite(db, "s-fail", "FAIL")
    client = TestClient(AgentOS(agents=[Agent(id="assistant", db=db)], db=db).get_app())

    body = client.get("/eval-runs", params={"status": "FAIL", "eval_types": "suite"}).json()
    assert [run["id"] for run in body["data"]] == ["s-fail"]
    assert body["meta"]["total_count"] == 1

    assert client.get("/eval-runs", params={"status": "nope"}).status_code == 422
