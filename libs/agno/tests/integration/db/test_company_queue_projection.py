"""Company Task projection failures must not hold queue tickets or the poll loop."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from agno.company.execution import _call
from agno.db.base import AsyncBaseDb
from tests.integration.db.test_company_execution_parity import accepted, automation, execute, tick
from tests.integration.db.test_company_execution_parity import system as execution_system

system = execution_system
pytestmark = pytest.mark.asyncio


def fail_task_writes(monkeypatch, db):
    mock = AsyncMock if isinstance(db, AsyncBaseDb) else Mock
    monkeypatch.setattr(db, "complete_task_run", mock(side_effect=RuntimeError("Company database unavailable")))


def expire_lease(worker, run_id, **values):
    queue_db = worker.config.db
    table = queue_db._get_table("jobs")
    with queue_db.Session() as session, session.begin():
        session.execute(table.update().where(table.c.id == run_id).values(locked_at=0, **values))


async def one_poll_tick(worker, monkeypatch):
    """Run exactly one sweep and its claim burst, executing whatever it claims."""
    sweep = worker._sweep_exhausted
    sweeps = []

    async def first_sweep_only():
        sweeps.append(1)
        if len(sweeps) > 1:
            worker._running = False
            return
        await sweep()

    async def stop():
        worker._running = False

    monkeypatch.setattr(worker, "_sweep_exhausted", first_sweep_only)
    monkeypatch.setattr(worker, "_wait_for_work", stop)
    worker._running = True
    await asyncio.wait_for(worker._poll_loop(), timeout=worker.config.poll_interval * 5)
    for running in list(worker._in_flight.values()):
        await running


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("recovery", ["automation", "http"])
async def test_persistent_task_write_failure_finishes_ticket(system, monkeypatch, outcome, recovery):
    client, db, worker, _, components = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    run_id = (await client.post(path + "/runs")).json()["run_id"]
    with monkeypatch.context() as outage:
        fail_task_writes(outage, db)
        if outcome == "failed":

            async def fail(*args, **kwargs):
                raise RuntimeError("executor failed")

            outage.setattr(components["writer"], "arun", fail)
            assert (await execute(worker))["status"] == "queued"
        elif outcome == "cancelled":
            # The CANCELLED run row is written; the ticket waits for its claim to settle it.
            assert not await worker.acancel_queued(run_id)
            assert (await worker.store.get_job(run_id))["status"] == "queued"
        # The ticket is held once; the sweep retries the write from the run row, then finishes it.
        assert (await execute(worker))["status"] == "running"
        expire_lease(worker, run_id, max_attempts=1)
        await worker._sweep_exhausted()
        assert (await worker.store.get_job(run_id))["status"] == outcome
        saved = await _call(db, "get_task", value["id"])
        assert saved["status"] == "in_progress" and saved["result"] is None
        # The outage persists: the finished ticket is not retried and the run is not replayed.
        assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
    expected = {"completed": "COMPLETED", "failed": "ERROR", "cancelled": "CANCELLED"}[outcome]
    if recovery == "automation":
        executor, _ = await automation(system)
        result = await tick(executor, db)
        assert result["output"]["tasks"][0]["action"] == "reconciled", result
    else:
        response = await client.post(path + "/runs")
        assert response.status_code == 202, response.text
    saved = await _call(db, "get_task", value["id"])
    assert saved["result"]["status"] == expected and saved["result"]["run_id"] == run_id
    assert saved["status"] == ("in_review" if outcome == "completed" else "in_progress")


async def test_cancelled_paused_ticket_finishes_when_task_write_fails(system, monkeypatch):
    client, db, worker, _, _ = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    run_id = (await client.post(path + "/runs")).json()["run_id"]
    claimed = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    # A run waiting on approval parks its ticket as paused, and no worker claims a paused ticket.
    assert await worker.store.complete_job(run_id, worker.worker_id, claimed["attempt"], "paused")
    with monkeypatch.context() as outage:
        fail_task_writes(outage, db)
        assert await worker.acancel_queued(run_id)
    assert (await worker.store.get_job(run_id))["status"] == "cancelled"
    assert (await client.post(path + "/runs")).status_code == 202
    assert (await _call(db, "get_task", value["id"]))["result"]["status"] == "CANCELLED"


async def test_swept_task_result_keeps_the_run_error(system, monkeypatch):
    client, db, worker, _, components = system
    value = await accepted(client)
    run_id = (await client.post(f"/company/tasks/{value['id']}/runs")).json()["run_id"]

    async def fail(*args, **kwargs):
        raise RuntimeError("executor failed")

    monkeypatch.setattr(components["writer"], "arun", fail)
    assert (await execute(worker))["status"] == "queued"
    with monkeypatch.context() as outage:
        fail_task_writes(outage, db)
        assert (await execute(worker))["status"] == "running"
    # The sweep saves the Task result with the run's own error, not its generic message.
    expire_lease(worker, run_id)
    await worker._sweep_exhausted()
    assert (await worker.store.get_job(run_id))["status"] == "failed"
    assert (await _call(db, "get_task", value["id"]))["result"]["content"] == "executor failed"


async def test_swept_task_result_ignores_a_partial_draft(system):
    from agno.agent._session import asave_run
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus

    client, db, worker, _, components = system
    value = await accepted(client)
    run_id = (await client.post(f"/company/tasks/{value['id']}/runs")).json()["run_id"]
    job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    # The worker dies mid-run, leaving a RUNNING row with a partial draft.
    run = RunOutput(
        run_id=run_id, session_id=job["session_id"], agent_id="writer", status=RunStatus.running, content="partial"
    )
    await asave_run(components["writer"], run=run, session_id=job["session_id"], user_id=job.get("user_id"))
    expire_lease(worker, run_id, max_attempts=1)
    await worker._sweep_exhausted()
    assert (await worker.store.get_job(run_id))["status"] == "failed"
    content = (await _call(db, "get_task", value["id"]))["result"]["content"]
    assert content.startswith("Worker lost and attempt budget exhausted")


async def test_refused_task_result_keeps_the_refusal_over_the_draft(system, monkeypatch):
    from agno.exceptions import CheckTrigger, OutputCheckError
    from agno.tools.scheduler import SchedulerTools

    client, db, worker, _, components = system
    value = await accepted(client)
    run_id = (await client.post(f"/company/tasks/{value['id']}/runs")).json()["run_id"]

    def reject(run_output):
        raise OutputCheckError("Draft failed review", check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED)

    monkeypatch.setattr(components["writer"], "post_hooks", [reject])
    assert (await execute(worker))["status"] == "queued"
    # The retry is refused, and the run row still holds the first attempt's draft.
    monkeypatch.setattr(components["writer"], "post_hooks", [])
    monkeypatch.setattr(components["writer"], "tools", [SchedulerTools(db=db)])
    job = await execute(worker)
    assert job["status"] == "failed"
    run = await components["writer"].aget_run_output(run_id, job["session_id"])
    assert run.content == "Completed evidence-based draft"
    saved = await _call(db, "get_task", value["id"])
    assert saved["result"]["content"] == "permanent: Company executors cannot hold SchedulerTools"


async def test_held_ticket_is_reclaimed_without_running_again(system, monkeypatch):
    client, db, worker, _, components = system
    value = await accepted(client)
    run_id = (await client.post(f"/company/tasks/{value['id']}/runs")).json()["run_id"]
    with monkeypatch.context() as outage:
        fail_task_writes(outage, db)
        assert (await execute(worker))["status"] == "running"
        executed = AsyncMock(side_effect=AssertionError("A completed Task run must not execute again"))
        outage.setattr(components["writer"], "arun", executed)
        # With attempts left, a reclaim settles from the COMPLETED run row and holds the ticket again.
        expire_lease(worker, run_id)
        job = await execute(worker)
        assert job["status"] == "running" and job["attempt"] == 2 and job["max_attempts"] == 2
        executed.assert_not_called()
    # The last attempt goes to the sweep, which saves the Task result and finishes the ticket.
    expire_lease(worker, run_id)
    await worker._sweep_exhausted()
    assert (await worker.store.get_job(run_id))["status"] == "completed"
    saved = await _call(db, "get_task", value["id"])
    assert saved["status"] == "in_review" and saved["result"]["status"] == "COMPLETED"


async def test_unresolvable_executor_cancel_raises_when_task_write_fails(system, monkeypatch):
    client, db, worker, _, _ = system
    value = await accepted(client)
    run_id = (await client.post(f"/company/tasks/{value['id']}/runs")).json()["run_id"]
    monkeypatch.setattr(worker, "resolve_component", lambda *args, **kwargs: None)
    with monkeypatch.context() as outage:
        fail_task_writes(outage, db)
        # No claim can reach the run row of an unresolvable executor, so the cancel cannot defer to it.
        with pytest.raises(RuntimeError, match="Company database unavailable"):
            await worker.acancel_queued(run_id)
    assert (await worker.store.get_job(run_id))["status"] == "queued"


async def test_unrecorded_reservation_keeps_ticket_for_recovery(system, monkeypatch):
    client, db, worker, _, _ = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    with monkeypatch.context() as outage:
        mock = AsyncMock if isinstance(db, AsyncBaseDb) else Mock
        outage.setattr(db, "start_task_run", mock(side_effect=RuntimeError("Company database unavailable")))
        # The ticket commits, then recording the Task's reservation fails.
        with pytest.raises(RuntimeError, match="Company database unavailable"):
            await client.post(path + "/runs")
        assert (await execute(worker))["status"] == "queued"
        run_id = (await execute(worker))["id"]
        assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "ERROR"
        assert (await _call(db, "get_task", value["id"]))["job_id"] is None
        # Recovery finds Tasks by their reservation, so the ticket must not finish without it.
        assert (await worker.store.get_job(run_id))["status"] == "running"
    expire_lease(worker, run_id)
    await worker._sweep_exhausted()
    assert (await worker.store.get_job(run_id))["status"] == "failed"
    saved = await _call(db, "get_task", value["id"])
    assert saved["job_id"] == run_id and saved["result"]["status"] == "ERROR"


@pytest.mark.parametrize("failure", ["task_write", "task_write_and_run_read"])
async def test_swept_company_failure_does_not_block_other_claims(system, monkeypatch, failure):
    import agno.company.execution as execution

    client, db, worker, _, components = system
    value = await accepted(client)
    swept_id = (await client.post(f"/company/tasks/{value['id']}/runs")).json()["run_id"]
    claimed = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert claimed["id"] == swept_id
    expire_lease(worker, swept_id, max_attempts=1)
    other = await client.post(
        "/teams/editors/runs", data={"message": "Unrelated work", "stream": "false", "background": "true"}
    )
    assert other.status_code == 202, other.text
    other_id = other.json()["run_id"]
    assert (await worker.store.get_job(other_id))["status"] == "queued"

    project = execution._project_run

    async def unavailable(worker, job, *args, **kwargs):
        if (job.get("payload") or {}).get("company_task_id"):
            raise RuntimeError("Company database unavailable")
        await project(worker, job, *args, **kwargs)

    async def unreadable(*args, **kwargs):
        raise RuntimeError("Run database unavailable")

    monkeypatch.setattr(execution, "_project_run", unavailable)
    if failure == "task_write_and_run_read":
        monkeypatch.setattr(components["writer"], "aget_run_output", unreadable)
    await one_poll_tick(worker, monkeypatch)
    assert (await worker.store.get_job(other_id))["status"] == "completed"
    swept = await worker.store.get_job(swept_id)
    if failure == "task_write":
        assert swept["status"] == "failed"
    else:
        # Kept under the sweep lock and retried once that lock goes stale.
        assert swept["status"] == "running"
        assert (await _call(db, "get_run", swept_id, deserialize=False))["status"] == "ERROR"


async def test_revoked_run_permission_fails_without_retry(system, monkeypatch):
    from agno.company.execution import _ExecutorAuthorization

    client, db, worker, _, components = system
    value = await accepted(client)
    run_id = (await client.post(f"/company/tasks/{value['id']}/runs")).json()["run_id"]
    calls = []

    async def revoked(self, resource, action, resource_id=None):
        calls.append((resource, action, resource_id))
        if resource == "agents" and action == "run":
            raise PermissionError("Run permission was revoked")

    monkeypatch.setattr(_ExecutorAuthorization, "arequire", revoked)
    executed = AsyncMock(side_effect=AssertionError("A revoked Task must not execute"))
    monkeypatch.setattr(components["writer"], "arun", executed)
    job = await execute(worker)
    assert ("agents", "run", "writer") in calls
    assert job["status"] == "failed" and job["attempt"] == 1 and job["max_attempts"] == 2
    assert job["error"].startswith("permanent:") and "revoked" in job["error"]
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
    assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "ERROR"
    assert (await _call(db, "get_task", value["id"]))["result"]["status"] == "ERROR"
    executed.assert_not_called()


async def test_scheduler_tools_added_after_queue_fails_without_retry(system, monkeypatch):
    from agno.tools.scheduler import SchedulerTools

    client, db, worker, _, components = system
    value = await accepted(client)
    run_id = (await client.post(f"/company/tasks/{value['id']}/runs")).json()["run_id"]
    # A redeploy can add SchedulerTools after the ticket was queued; retrying cannot cure that.
    monkeypatch.setattr(components["writer"], "tools", [SchedulerTools(db=db)])
    job = await execute(worker)
    assert job["status"] == "failed" and job["attempt"] == 1 and job["max_attempts"] == 2
    assert job["error"] == "permanent: Company executors cannot hold SchedulerTools"
    assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "ERROR"
    assert (await _call(db, "get_task", value["id"]))["result"]["status"] == "ERROR"
