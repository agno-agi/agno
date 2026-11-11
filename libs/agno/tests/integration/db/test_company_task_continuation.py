"""A finished attempt's evidence stays in its run; a person's reply continues the same Task and session once."""

import json

import pytest

from agno.company.evidence import run_evidence
from agno.company.execution import _call
from agno.db.schemas.tasks import task_run_id
from tests.integration.db.test_company_execution_parity import accepted, execute, system  # noqa: F401


@pytest.mark.asyncio
async def test_reply_continues_the_same_session_once(system):  # noqa: F811
    client, db, worker, _, _ = system
    task = await accepted(client, "workflow", "draft")
    path = f"/company/tasks/{task['id']}"
    assert (await client.post(path + "/runs")).status_code == 202
    assert (await execute(worker))["status"] == "completed"

    reviewed = (await client.get(path)).json()
    assert reviewed["status"] == "in_review"
    # The Task keeps only the result; what the run did is read from the run.
    assert "evidence" not in reviewed["result"]
    run = (await client.get(f"/company/runs/{reviewed['result']['run_id']}")).json()
    evidence, _ = run_evidence(run["run_data"])
    assert evidence and evidence[0]["kind"] == "step" and evidence[0]["name"] == "Draft"

    reply = {"message": "Go with option A", "in_reply_to_attempt": 1}
    continued = await client.post(path + "/continue", json=reply)
    assert continued.status_code == 202, continued.text
    second = task_run_id(task["id"], 2)
    assert continued.json()["run_id"] == second

    job = await worker.store.get_job(second)
    assert job["session_id"] == task["session_id"]
    payload = json.loads(job["payload"]["input"])
    assert payload["follow_up"]["message"] == "Go with option A" and payload["follow_up"]["in_reply_to_attempt"] == 1
    assert payload["previous_result"]["status"] == "COMPLETED"
    assert "act on follow_up" in payload["execution_context"]["instructions"]
    started = (await _call(db, "get_task", task["id"]))["transitions"][-1]
    assert started["attempt"] == 2 and started["follow_up"]["message"] == "Go with option A"

    # The same reply again joins its attempt; a different one cannot take it over.
    again = await client.post(path + "/continue", json=reply)
    assert again.status_code == 202 and again.json()["run_id"] == second
    other = await client.post(path + "/continue", json={"message": "Go with option B", "in_reply_to_attempt": 1})
    assert other.status_code == 409
    attempts = [entry for entry in (await _call(db, "get_task", task["id"]))["transitions"] if entry.get("attempt")]
    assert [entry["attempt"] for entry in attempts] == [1, 2]

    # Once attempt 2 finishes, a late reply to attempt 1 is superseded and starts nothing.
    assert (await execute(worker))["status"] == "completed"
    late = await client.post(path + "/continue", json={"message": "Option B after all", "in_reply_to_attempt": 1})
    assert late.status_code == 409 and "superseded" in late.json()["detail"]
    assert await worker.store.get_job(task_run_id(task["id"], 3)) is None

    done = await client.post(path + "/transitions", json={"target": "done", "reason": "Accepted"})
    assert done.status_code == 200, done.text
    closed = await client.post(path + "/continue", json={"message": "One more thing"})
    assert closed.status_code == 409 and "done" in closed.json()["detail"]


@pytest.mark.asyncio
async def test_reply_needs_a_finished_attempt(system):  # noqa: F811
    client, _, worker, _, _ = system
    task = await accepted(client, "workflow", "draft")
    path = f"/company/tasks/{task['id']}"
    unstarted = await client.post(path + "/continue", json={"message": "Hello"})
    assert unstarted.status_code == 409 and "not run yet" in unstarted.json()["detail"]

    assert (await client.post(path + "/runs")).status_code == 202
    running = await client.post(path + "/continue", json={"message": "Faster please"})
    assert running.status_code == 409 and "still running" in running.json()["detail"]
    assert await worker.store.get_job(task_run_id(task["id"], 2)) is None
