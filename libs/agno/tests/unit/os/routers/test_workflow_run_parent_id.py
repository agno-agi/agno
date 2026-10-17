"""Nested workflow runs retain their parent identity in session read APIs."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.os.routers.session.session import get_session_router
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput


def echo(step_input: StepInput) -> StepOutput:
    return StepOutput(content=str(step_input.input))


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("stream", [False, True], ids=["non-streaming", "streaming"])
@pytest.mark.parametrize("store_executor_outputs", [False, True])
async def test_nested_workflow_parent_id_in_session_runs(
    tmp_path, async_mode: bool, stream: bool, store_executor_outputs: bool
):
    db = SqliteDb(id="test-db", db_file=str(tmp_path / "sessions.db"))
    child = Workflow(id="child", db=db, telemetry=False, steps=[Step(name="Draft", executor=echo)])
    parent = Workflow(
        id="parent",
        db=db,
        telemetry=False,
        store_executor_outputs=store_executor_outputs,
        steps=[Step(name="Child", workflow=child)],
    )
    kwargs = dict(input="release", session_id="session", run_id="parent-run", stream=stream)
    if async_mode:
        if stream:
            async for _ in parent.arun(**kwargs):
                pass
        else:
            await parent.arun(**kwargs)
    elif stream:
        list(parent.run(**kwargs))
    else:
        parent.run(**kwargs)

    app = FastAPI()
    app.include_router(get_session_router({"test-db": [db]}))
    with TestClient(app) as client:
        for params in ({"db_id": "test-db", "type": "workflow"}, {"db_id": "test-db"}):
            response = client.get("/sessions/session/runs", params=params)
            assert response.status_code == 200, response.text
            runs = response.json()
            assert len(runs) == 2
            parent_run = next(run for run in runs if run["run_id"] == "parent-run")
            child_run = next(run for run in runs if run["workflow_id"] == "child")
            assert "parent_run_id" not in parent_run
            assert child_run["parent_run_id"] == parent_run["run_id"]
            assert parent_run["step_results"][0]["step_run_id"] == child_run["run_id"]

            response = client.get(f"/sessions/session/runs/{child_run['run_id']}", params=params)
            assert response.status_code == 200, response.text
            assert response.json()["parent_run_id"] == parent_run["run_id"]
