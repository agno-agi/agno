"""Stable Task ownership, policy-independent recovery and bounded diagnostics."""

import asyncio
import time
from unittest.mock import AsyncMock

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from agno.company.execution import _call, _recover_task
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from agno.run import RunStatus
from agno.run.cancel import acleanup_run, aregister_run
from tests.integration.db.test_company_execution_parity import accepted, automation, execute, routine_proposal, tick
from tests.integration.db.test_company_execution_parity import system as execution_system
from tests.integration.db.test_company_failure_recovery import delete_ticket

system = execution_system


@pytest.mark.asyncio
@pytest.mark.parametrize("isolation", [False, True])
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("kind,executor_id", [("agent", "writer"), ("team", "editors"), ("workflow", "draft")])
async def test_collaborators_share_task_owner_and_preserve_actor_authority(
    system, tmp_path, monkeypatch, isolation, managed, kind, executor_id
):
    _, db, worker, _, components = system
    secret = "company-task-identity-secret-at-least-32-bytes"
    scopes = [f"{resource}:{action}" for resource in ("products", "projects", "tasks") for action in ("read", "write")]
    scopes += [kind + "s:run", "wiki:read"]
    auth_db = SqliteDb(db_file=str(tmp_path / "identity.db"))
    authz = Authorization(db=auth_db if managed else None, verification_keys=[secret], algorithm="HS256")
    if managed:
        authz.define_role("admin", ["agent_os:admin"])
        authz.define_role("runner", scopes)
        authz.define_role("reader", [scope for scope in scopes if not scope.endswith(":run")])
        authz.seed(admin="root")
        authz.assign("alice", "runner")
        authz.assign("bob", "runner")
        authz.assign("denied", "reader")

    def headers(user):
        claims = {"sub": user, "aud": "identity-test", "exp": int(time.time()) + 3600}
        if not managed:
            claims["scopes"] = scopes if user != "denied" else [scope for scope in scopes if not scope.endswith(":run")]
        return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm="HS256")}

    os_app = AgentOS(
        id="identity-test",
        db=db,
        agents=[components["writer"]],
        teams=[components["editors"]],
        workflows=[components["draft"]],
        company=CompanyConfig(),
        queue=worker.config,
        authorization=authz,
        user_isolation=isolation,
        telemetry=False,
    )
    app = os_app.get_app()
    app.state.queue_worker = worker
    app.state.internal_service_token = "test"
    worker.authorization_app = app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers("alice")
    ) as client:
        task = await accepted(client, kind, executor_id)
        path = "/company/tasks/" + task["id"]
        first = await client.post(path + "/runs")
        assert first.status_code == 202, first.text
        assert (await execute(worker))["status"] == "completed"
        denied = await client.post(path + "/runs", json={"attempt": 2}, headers=headers("denied"))
        assert denied.status_code == 403, denied.text
        second = await client.post(path + "/runs", json={"attempt": 2}, headers=headers("bob"))
        assert second.status_code == 202, second.text
        assert second.json()["session_id"] == first.json()["session_id"]
        with monkeypatch.context() as failure:

            def unavailable(*args, **kwargs):
                raise RuntimeError("Lost second-attempt projection")

            failure.setattr(db, "complete_task_run", unavailable)
            await execute(worker)
        delete_ticket(worker, second.json()["run_id"])
        executor, _ = await automation((client, db, worker, os_app, components))
        assert (await executor._tick())[0]["action"] == "reconciled"
        current = await _call(db, "get_task", task["id"])
        starts = [entry for entry in current["transitions"] if entry.get("attempt")]
        assert [entry["started_by"] for entry in starts] == ["alice", "bob"]
        for response in (first, second):
            run = await _call(db, "get_run", response.json()["run_id"], deserialize=False)
            assert run["user_id"] == task["user_id"] == "alice"
        session = await _call(
            db, "get_session", current["session_id"], session_type=SessionType(kind), deserialize=False
        )
        assert session["user_id"] == "alice"
        # Bob accepts the retry, but the session still belongs to Alice.
        for target, extra in [("backlog", {}), ("ready", {"executor_type": kind, "executor_id": executor_id})]:
            response = await client.post(
                path + "/transitions",
                headers=headers("bob"),
                json={"target": target, "reason": "Retry with current authority", **extra},
            )
            assert response.status_code == 200, response.text
        executor, _ = await automation((client, db, worker, os_app, components))
        outcomes = await executor._tick()
        assert outcomes[0]["action"] == "submitted", outcomes
        assert (await execute(worker))["status"] == "completed"
        current = await _call(db, "get_task", task["id"])
        assert current["transitions"][-2]["started_by"] == "bob"
        assert (await _call(db, "get_run", current["job_id"], deserialize=False))["user_id"] == "alice"
        assert await _call(
            db, "reassign_session_owner", current["session_id"], previous_user_id="alice", user_id="unrelated"
        )
        refused = await client.post(path + "/runs", json={"attempt": 4}, headers=headers("bob"))
        assert refused.status_code == 404, refused.text
    auth_db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["paused", "revoked"])
@pytest.mark.parametrize("finished", [False, True])
async def test_recovery_ignores_current_routine_policy(system, tmp_path, monkeypatch, change, finished):
    client, db, worker, os_app, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    executor, _ = await automation(system)
    assert (await executor._tick())[0]["status"] == "accepted"
    current = await _call(db, "get_task", task["id"])
    if finished:
        with monkeypatch.context() as failure:
            failure.setattr(
                db,
                "complete_task_run",
                AsyncMock(side_effect=RuntimeError("Lost projection"))
                if asyncio.iscoroutinefunction(db.complete_task_run)
                else lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Lost projection")),
            )
            await execute(worker)
    delete_ticket(worker, current["job_id"])
    if change == "paused":
        await _call(db, "update_schedule", routine["id"], enabled=False)
    else:
        payload = routine["payload"]
        payload["metadata"]["auto_accept"] = None
        await _call(db, "update_schedule", routine["id"], payload=payload)
    monkeypatch.setattr(worker.store, "enqueue_job", AsyncMock(side_effect=AssertionError("Recovery must not enqueue")))
    outcomes = await executor._tick()
    assert outcomes[0]["action"] == "reconciled", outcomes
    current = await _call(db, "get_task", task["id"])
    assert current["result"]["status"] == ("COMPLETED" if finished else "CANCELLED")


@pytest.mark.asyncio
@pytest.mark.parametrize("live", [False, True])
async def test_ticketless_running_is_observed_without_authoritative_liveness(system, monkeypatch, live):
    client, db, worker, os_app, _ = system
    task = await accepted(client)
    started = await client.post("/company/tasks/" + task["id"] + "/runs")
    run_id = started.json()["run_id"]
    run = await _call(db, "get_run", run_id)
    run.status = RunStatus.running
    await _call(db, "upsert_run", run, session_id=task["session_id"])
    delete_ticket(worker, run_id)
    if live:
        await aregister_run(run_id)
    else:
        await acleanup_run(run_id)
    monkeypatch.setattr(worker.store, "enqueue_job", AsyncMock(side_effect=AssertionError("Do not replay tools")))
    try:
        result = await _recover_task(os_app, worker, await _call(db, "get_task", task["id"]))
        assert result["status"] == "RUNNING"
        assert result["action"] == "observed"
        assert (await _call(db, "get_task", task["id"]))["result"] is None
    finally:
        await acleanup_run(run_id)


@pytest.mark.asyncio
async def test_failure_streaks_attention_and_retention(system, monkeypatch):
    client, db, worker, os_app, _ = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    failure = AsyncMock(side_effect=RuntimeError("Unavailable run database"))
    monkeypatch.setattr(executor, "_dispatch", failure)
    for _ in range(3):
        await _call(db, "update_schedule", schedule["id"], next_run_at=0)
        assert (await tick(executor, db))["status"] == "failed"
    rows, count = await _call(db, "get_schedule_runs", schedule["id"])
    assert count == 1
    attention = (await client.get("/company/attention")).json()
    assert attention["automation_failures"] == [
        {"task_id": task["id"], "reason": "Unavailable run database", "count": 3}
    ]
    failure.side_effect = RuntimeError("Queue unavailable")
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    await tick(executor, db)
    attention = (await client.get("/company/attention")).json()
    assert attention["automation_failures"][0]["count"] == 1
    assert attention["failed"] == 1
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    await tick(executor, db)
    assert (await client.get("/company/attention")).json()["automation_failures"][0]["count"] == 2
    await _call(db, "transition_task", task["id"], "backlog", "Replan")
    await _call(db, "transition_task", task["id"], "ready", "Accept again", executor_type="agent", executor_id="writer")
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    await tick(executor, db)
    assert (await client.get("/company/attention")).json()["automation_failures"][0]["count"] == 1
    await _call(db, "transition_task", task["id"], "cancelled", "Stop")
    assert "automation_failures" not in (await client.get("/company/attention")).json()
    await _call(db, "update_schedule_run", rows[0]["id"], completed_at=int(time.time()) - 31 * 86400)
    from agno.company.manager import AsyncCompanyManager, CompanyManager
    from agno.db.base import AsyncBaseDb

    manager = AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db)
    result = await _call(manager, "refresh", task["product_id"])
    assert result["deleted_automation_runs"] == 1
    assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [7, 30])
async def test_refresh_tool_applies_company_history_retention(system, days):
    import json
    from uuid import uuid4

    from agno.company.routines import _RoutineAuthorization
    from agno.db.schemas.scheduler import ScheduleRun
    from agno.run.authorization import authorization_scope
    from agno.tools.company import CompanyTools

    client, db, _, os_app, components = system
    task = await accepted(client)
    _, schedule = await automation(system)
    tool = CompanyTools(db)
    components["writer"].tools = [tool]
    os_app.company.automation_history_retention_days = days
    os_app._bind_company_tools()
    now = int(time.time())
    old_id, recent_id, running_id = [str(uuid4()) for _ in range(3)]
    for run_id, age, finished in [(old_id, days + 1, True), (recent_id, days - 1, True), (running_id, days + 1, False)]:
        await _call(
            db,
            "create_schedule_run",
            ScheduleRun(
                id=run_id,
                schedule_id=schedule["id"],
                triggered_at=now - age * 86400,
                completed_at=now - age * 86400 if finished else None,
                status="success" if finished else "running",
            ).to_dict(),
        )
    with authorization_scope(lambda: _RoutineAuthorization(None, product_id=task["product_id"])):
        result = json.loads(await tool.arefresh_company_product(task["product_id"]))
    assert result["deleted_automation_runs"] == 1
    rows, count = await _call(db, "get_schedule_runs", schedule["id"])
    assert count == 2 and {row["id"] for row in rows} == {recent_id, running_id}


@pytest.mark.asyncio
async def test_acceptance_and_dispatch_failure_record_the_failure_once(system, tmp_path, monkeypatch):
    _, db, _, _, _ = system
    task, _, _ = await routine_proposal(system, tmp_path)
    executor, schedule = await automation(system)
    monkeypatch.setattr(executor, "_dispatch", AsyncMock(side_effect=RuntimeError("Executor unavailable")))
    for count in (1, 2):
        await _call(db, "update_schedule", schedule["id"], next_run_at=0)
        result = await tick(executor, db)
        assert result["status"] == "failed"
        rows, total = await _call(db, "get_schedule_runs", schedule["id"])
        failures = [row for row in rows if row["status"] == "failed"]
        assert total == 2 and len(failures) == 1
        assert failures[0]["output"]["automation_failure"]["count"] == count
        assert failures[0]["output"]["automation_failure"]["task_id"] == task["id"]


@pytest.mark.asyncio
async def test_worker_projection_and_recovery_settle_once(system, monkeypatch):
    from agno.company.execution import _project_run

    client, db, worker, os_app, _ = system
    task = await accepted(client)
    response = await client.post("/company/tasks/" + task["id"] + "/runs")
    run_id = response.json()["run_id"]
    with monkeypatch.context() as failure:

        def unavailable(*args, **kwargs):
            raise RuntimeError("Projection unavailable")

        failure.setattr(db, "complete_task_run", unavailable)
        job = await execute(worker)
    reserved = await _call(db, "get_task", task["id"])
    delete_ticket(worker, run_id)
    await asyncio.gather(_project_run(worker, job, "completed"), _recover_task(os_app, worker, reserved))
    saved = await _call(db, "get_task", task["id"])
    assert saved["status"] == "in_review"
    assert saved["result"]["status"] == "COMPLETED"
    assert len(saved["transitions"]) == len(reserved["transitions"]) + 1
    assert (
        await _call(
            db,
            "complete_task_run",
            task["id"],
            run_id,
            {"status": "ERROR"},
            expected_transitions=reserved["transitions"],
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("statuses", [("ERROR", "COMPLETED"), ("CANCELLED", "ERROR"), ("COMPLETED", "CANCELLED")])
async def test_competing_terminal_results_preserve_one_winner(system, statuses):
    client, db, _, _, _ = system
    task = await accepted(client)
    assert (await client.post("/company/tasks/" + task["id"] + "/runs")).status_code == 202
    reserved = await _call(db, "get_task", task["id"])
    results = [{"run_id": reserved["job_id"], "status": status, "content": status} for status in statuses]
    outcomes = await asyncio.gather(
        *[
            _call(
                db,
                "complete_task_run",
                task["id"],
                reserved["job_id"],
                result,
                expected_transitions=reserved["transitions"],
            )
            for result in results
        ]
    )
    winners = [outcome for outcome in outcomes if outcome is not None]
    assert len(winners) == 1
    saved = await _call(db, "get_task", task["id"])
    assert saved["result"] == winners[0]["result"]
    assert saved["status"] == ("in_review" if saved["result"]["status"] == "COMPLETED" else "in_progress")


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_ticket", [False, True])
async def test_legacy_starter_session_recovers_then_adopts_accountable_owner(system, legacy_ticket):
    from agno.company.execution import _reserve_task
    from agno.db.base import AsyncBaseDb
    from agno.db.schemas.tasks import task_run_id
    from agno.run.agent import RunOutput
    from agno.session.agent import AgentSession

    client, db, worker, os_app, _ = system
    task = await accepted(client)
    task = await _call(db, "get_task", task["id"])
    if legacy_ticket:
        reserved = await _reserve_task(
            db,
            {
                "id": task_run_id(task["id"], 1),
                "user_id": "legacy-starter",
                "payload": {
                    "company_task_id": task["id"],
                    "company_task_attempt": 1,
                    "company_task_transitions": task["transitions"],
                    "company_run_db_id": db.id,
                },
            },
        )
        assert reserved["transitions"][-1]["session_user_id"] == "legacy-starter"
    else:
        reserved = await _call(
            db, "start_task_run", task["id"], 1, task["transitions"], user_id="legacy-starter", run_db_id=db.id
        )
        reserved["transitions"][-1].pop("started_by")
        reserved["transitions"][-1].pop("session_user_id")
    table = await _call(db, "_get_table", table_type="tasks")
    statement = (
        table.update()
        .where(table.c.id == task["id"])
        .values(user_id="accountable-owner", transitions=reserved["transitions"])
    )
    if isinstance(db, AsyncBaseDb):
        async with db.async_session_factory() as session, session.begin():
            await session.execute(statement)
    else:
        with db.Session() as session, session.begin():
            session.execute(statement)
    await _call(
        db,
        "upsert_session",
        AgentSession(
            session_id=task["session_id"], agent_id="writer", user_id="legacy-starter", created_at=int(time.time())
        ),
    )
    await _call(
        db,
        "upsert_run",
        RunOutput(
            run_id=reserved["job_id"],
            session_id=task["session_id"],
            agent_id="writer",
            user_id="legacy-starter",
            status=RunStatus.completed,
            content="Legacy result",
        ),
        session_id=task["session_id"],
        user_id="legacy-starter",
    )
    outcome = await _recover_task(os_app, worker, await _call(db, "get_task", task["id"]))
    assert outcome["action"] == "reconciled"
    response = await client.post("/company/tasks/" + task["id"] + "/runs", json={"attempt": 2})
    assert response.status_code == 202, response.text
    assert response.json()["session_id"] == task["session_id"]
    assert (await execute(worker))["status"] == "completed"
    saved = await _call(db, "get_session", task["session_id"], session_type=SessionType.AGENT, deserialize=False)
    assert saved["user_id"] == "accountable-owner"
    assert (await _call(db, "get_run", response.json()["run_id"], deserialize=False))["user_id"] == "accountable-owner"
