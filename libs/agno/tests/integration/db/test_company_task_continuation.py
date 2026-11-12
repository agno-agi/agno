"""A finished attempt's evidence stays in its run; a sent-back Task starts again on its session, once."""

import json

import pytest

from agno.company.evidence import run_evidence
from agno.company.execution import _call, _review_feedback
from agno.db.schemas.tasks import task_run_id
from tests.integration.db.test_company_execution_parity import accepted, execute, system  # noqa: F401


@pytest.mark.asyncio
async def test_a_sent_back_task_starts_again_on_its_session_once(system):  # noqa: F811
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

    # A reply is a send-back: back to Ready with the person's words, the same executor, then a start.
    back = {"target": "ready", "reason": "Go with option A", "executor_type": "workflow", "executor_id": "draft"}
    sent = await client.post(path + "/transitions", json=back)
    assert sent.status_code == 200, sent.text
    started = await client.post(path + "/runs")
    assert started.status_code == 202, started.text
    second = task_run_id(task["id"], 2)
    assert started.json()["run_id"] == second
    # Starting again joins the same attempt.
    again = await client.post(path + "/runs")
    assert again.status_code == 202 and again.json()["run_id"] == second

    job = await worker.store.get_job(second)
    assert job["session_id"] == task["session_id"]
    payload = json.loads(job["payload"]["input"])
    assert payload["review_feedback"] == "Go with option A"
    assert payload["previous_result"]["status"] == "COMPLETED"
    assert "act on review_feedback" in payload["execution_context"]["instructions"]
    attempts = [entry for entry in (await _call(db, "get_task", task["id"]))["transitions"] if entry.get("attempt")]
    assert [entry["attempt"] for entry in attempts] == [1, 2]

    # Once attempt 2 reaches review, the reason is spent: a later attempt is not told about it.
    assert (await execute(worker))["status"] == "completed"
    finished = await _call(db, "get_task", task["id"])
    assert finished["status"] == "in_review"
    assert _review_feedback(finished) is None
