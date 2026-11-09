"""Deterministic delegated lifecycle through real APIs and PostgreSQL queue tickets."""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from agno.agent import Agent
from agno.company.lifecycle import CompanyLifecycleTools
from agno.company.routines import _CompanyScheduleExecutor
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, Authorization, CompanyConfig
from agno.os.job_queue import QueueWorker, resolve_queue_store
from agno.run import RunContext

SECRET = "company-managed-lifecycle-test-secret-32-bytes"
SCOPES = [
    "agents:company--manager:run",
    "products:read",
    "products:write",
    "projects:read",
    "projects:write",
    "tasks:read",
    "tasks:write",
    "wiki:read",
    "company:read",
    "agents:writer:run",
]


def headers(user="alice"):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": user, "aud": "lifecycle", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            SECRET,
            algorithm="HS256",
        )
    }


class OfflineModel(Model):
    def __init__(self, kind="coordinator"):
        super().__init__(id="offline-lifecycle", provider="test")
        self.kind = kind
        self.attempts = 0
        self.always_revise = False
        self.bad_evidence = False
        self.question = False
        self.started = None
        self.release = None

    def invoke(self, messages, **kwargs):
        content = next(str(message.content) for message in reversed(messages) if message.role == "user")
        if self.kind == "assessor":
            payload = json.loads(content)
            evidence = payload["evidence"]
            done = (
                self.bad_evidence
                or payload["kind"] == "project"
                or ("version=2" in json.dumps(evidence) and not self.always_revise)
            )
            result = {
                "decision": "question" if self.question else "done" if done else "revise",
                "reason": "The checked artifact satisfies the outcome" if done else "The artifact needs version 2",
                "evidence": ["invented"] if self.bad_evidence else list(evidence),
                "next_instruction": None if done else "Produce and verify version=2",
            }
            return ModelResponse(role="assistant", content=json.dumps(result), response_usage=MessageMetrics())
        if self.kind == "worker":
            last_user = max(i for i, message in enumerate(messages) if message.role == "user")
            results = [message.content for message in messages[last_user + 1 :] if message.role == "tool"]
            if results:
                return ModelResponse(role="assistant", content=str(results[-1]), response_usage=MessageMetrics())
            self.attempts += 1
            version = 2 if '"revision"' in content else 1
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "verify-artifact",
                        "type": "function",
                        "function": {
                            "name": "write_and_verify_artifact",
                            "arguments": json.dumps({"version": version}),
                        },
                    }
                ],
                response_usage=MessageMetrics(),
            )
        last_user = max(i for i, message in enumerate(messages) if message.role == "user")
        if content == "status":
            result = [message.content for message in messages[last_user + 1 :] if message.role == "tool"]
            if result:
                return ModelResponse(role="assistant", content=str(result[-1]), response_usage=MessageMetrics())
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "task-status",
                        "type": "function",
                        "function": {
                            "name": "list_company_tasks",
                            "arguments": "{}",
                        },
                    }
                ],
                response_usage=MessageMetrics(),
            )
        if any(message.role == "tool" for message in messages[last_user + 1 :]) or content != "delegate":
            return ModelResponse(
                role="assistant",
                content="Receipt recorded" if content == "delegate" else "Unrelated answer",
                response_usage=MessageMetrics(),
            )
        return ModelResponse(
            role="assistant",
            tool_calls=[
                {
                    "id": "delegate-call",
                    "type": "function",
                    "function": {
                        "name": "delegate_company_outcome",
                        "arguments": json.dumps(
                            {
                                "product_name": "SDK",
                                "outcome": "A verified version=2 artifact",
                                "title": "Deliver artifact",
                                "brief": "Produce a checked artifact with version=2",
                                "executor_type": "agent",
                                "executor_id": "writer",
                            }
                        ),
                    },
                }
            ],
            response_usage=MessageMetrics(),
        )

    async def ainvoke(self, *args, **kwargs):
        if self.started is not None:
            self.started.set()
            await self.release.wait()
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.fixture
async def system(tmp_path):
    schema = "managed_lifecycle_" + uuid4().hex
    url = os.environ.get("COMPANY_TEST_DB_URL", "postgresql+psycopg://agno:agno@127.0.0.1:5532/agno")
    db = PostgresDb(db_url=url, db_schema=schema)
    worker_model = OfflineModel("worker")

    def write_and_verify_artifact(version: int) -> str:
        """Write a fixture artifact and independently read its bytes back for verification."""
        from hashlib import sha256

        path = tmp_path / f"artifact-{version}.txt"
        path.write_text(f"version={version}")
        content = path.read_text()
        assert content == f"version={version}"
        return json.dumps(
            {"artifact": str(path), "content": content, "verified_sha256": sha256(path.read_bytes()).hexdigest()}
        )

    writer = Agent(id="writer", db=db, model=worker_model, tools=[write_and_verify_artifact], telemetry=False)
    auth = Authorization(db=db, verification_keys=[SECRET], algorithm="HS256", audience="lifecycle")
    auth.define_role("delegator", SCOPES).assign("alice", "delegator")
    config = QueueConfig(durable=True, db=db, max_attempts=1)
    host = AgentOS(
        id="lifecycle",
        db=db,
        agents=[writer],
        company=CompanyConfig(model=OfflineModel()),
        authorization=auth,
        scheduler=True,
        queue=config,
        telemetry=False,
        user_isolation=True,
    )
    assessor = OfflineModel("assessor")
    host._company_assessor.model = assessor
    app = host.get_app()
    components = {agent.id: agent for agent in host.agents}
    worker = QueueWorker(
        resolve_queue_store(config, db),
        lambda kind, component_id, scope=None: components.get(component_id),
        config,
        authorization_app=app,
    )
    worker._company_db = db
    worker._company_schedule_db = db
    app.state.queue_worker = worker
    executor = _CompanyScheduleExecutor(
        host,
        app,
        company_db=db,
        schedule_db=db,
        base_url="http://test",
        internal_service_token=host._internal_service_token,
    )
    app.state.scheduler_executor = executor
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield host, db, worker, executor, client, auth, assessor, worker_model
    with db.db_engine.begin() as conn:
        conn.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
    db.close()


async def execute(worker):
    # Follow the real poller's due-time behavior: enqueue and claim may use
    # different clocks on opposite sides of an epoch-second boundary.
    deadline = asyncio.get_running_loop().time() + 2
    job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    while job is None and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
        job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert job is not None
    await worker._execute_claimed(job)
    return await worker.store.get_job(job["id"])


async def delegate(system):
    host, db, worker, executor, client, auth, assessor, worker_model = system
    response = await client.post(
        "/agents/company--manager/runs",
        headers=headers(),
        data={"message": "delegate", "session_id": "conversation", "stream": "false"},
    )
    assert response.status_code == 200, response.text
    tasks, total = db.get_tasks()
    assert total == 1, response.text
    task = tasks[0]
    assert task["status"] == "in_progress", response.text
    assert task["accepted_by"] == "alice"
    assert task["session_id"] != "conversation"
    assert any(entry.get("system_decision", {}).get("operation") == "accept" for entry in task["transitions"])
    return task


@pytest.mark.asyncio
async def test_delegate_revision_and_completion_without_human_approvals(system):
    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    reply = await client.post(
        "/agents/company--manager/runs",
        headers=headers(),
        data={"message": "unrelated", "session_id": "conversation", "stream": "false"},
    )
    assert reply.status_code == 200 and "Unrelated answer" in reply.text
    first = await execute(worker)
    assert first["status"] == "completed"
    revised = db.get_task(task["id"])
    assert revised["status"] == "in_progress", revised
    assert revised["session_id"] == task["session_id"]
    second = await execute(worker)
    assert second["status"] == "completed"
    finished = db.get_task(task["id"])
    assert finished["status"] == "done", finished
    assert db.get_project(task["project_id"])["status"] == "done", db.get_project(task["project_id"])
    assert worker_model.attempts == 2
    await executor._tick()
    assert worker_model.attempts == 2


@pytest.mark.asyncio
async def test_revoked_authority_never_completes_or_revises(system):
    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    auth.set_role_scopes("delegator", [scope for scope in SCOPES if scope != "tasks:write"])
    await execute(worker)
    current = db.get_task(task["id"])
    assert current["status"] != "done"
    assert len([entry for entry in current["transitions"] if "attempt" in entry]) == 1
    assert db.get_project(task["project_id"])["status"] == "active"


@pytest.mark.asyncio
async def test_exhausted_revisions_surface_backlog_without_new_execution(system):
    host, db, worker, executor, client, auth, assessor, worker_model = system
    assessor.always_revise = True
    task = await delegate(system)
    for _ in range(3):
        await execute(worker)
    current = db.get_task(task["id"])
    assert current["status"] == "backlog"
    assert "limit exhausted" in current["transitions"][-1]["reason"]
    await executor._tick()
    assert worker_model.attempts == 3


@pytest.mark.asyncio
async def test_arbitrary_component_cannot_use_lifecycle_tool(system):
    host, db, worker, executor, client, auth, assessor, worker_model = system
    toolkit = next(tool for tool in host.company_manager.tools if isinstance(tool, CompanyLifecycleTools))
    with pytest.raises(PermissionError, match="framework manager"):
        await toolkit.aactivate_company_project(
            "missing",
            _agno_agent=host.agents[0],
            _agno_run_context=RunContext(run_id="r", session_id="s", user_id="alice"),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["bad_evidence", "question"])
async def test_missing_input_and_fabricated_verification_stop_execution(system, mode):
    host, db, worker, executor, client, auth, assessor, worker_model = system
    setattr(assessor, mode, True)
    task = await delegate(system)
    await execute(worker)
    current = db.get_task(task["id"])
    assert current["status"] == "backlog"
    decision = current["transitions"][-1]["system_decision"]
    assert decision["decision"] == ("question" if mode == "question" else "failed")
    assert decision["reason"]
    await executor._tick()
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
    assert worker_model.attempts == 1


@pytest.mark.asyncio
async def test_restart_reconciles_persisted_completion_once(system):
    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    del executor.app.state.scheduler_executor
    await execute(worker)
    assert db.get_task(task["id"])["status"] == "in_review"
    # A fresh scheduler has no in-memory lifecycle state; it reads the existing
    # Task, persisted run evidence and acceptance authority from PostgreSQL.
    recovered = _CompanyScheduleExecutor(
        host,
        executor.app,
        company_db=db,
        schedule_db=db,
        base_url="http://test",
        internal_service_token=host._internal_service_token,
    )
    executor.app.state.scheduler_executor = recovered
    await recovered._tick()
    revised = db.get_task(task["id"])
    assert revised["status"] == "in_progress"
    await recovered._tick()
    await execute(worker)
    assert db.get_task(task["id"])["status"] == "done"
    assert db.get_project(task["project_id"])["status"] == "done"
    assert worker_model.attempts == 2


@pytest.mark.asyncio
async def test_cancellation_during_assessment_is_not_overwritten(system, monkeypatch):
    import agno.company.lifecycle as lifecycle

    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    original = lifecycle._assess

    async def cancel_after_assessment(*args, **kwargs):
        assessment = await original(*args, **kwargs)
        response = await client.post(
            f"/company/tasks/{task['id']}/transitions",
            headers=headers(),
            json={"target": "cancelled", "reason": "User cancelled"},
        )
        assert response.status_code == 200, response.text
        return assessment

    monkeypatch.setattr(lifecycle, "_assess", cancel_after_assessment)
    await execute(worker)
    assert db.get_task(task["id"])["status"] == "cancelled"
    await executor._tick()
    assert db.get_task(task["id"])["status"] == "cancelled"
    assert worker_model.attempts == 1


@pytest.mark.asyncio
async def test_executor_permission_denial_creates_no_work(system):
    host, db, worker, executor, client, auth, assessor, worker_model = system
    auth.define_role("conversation-only", ["agents:company--manager:run", "company:read"]).assign(
        "bob", "conversation-only"
    )
    response = await client.post(
        "/agents/company--manager/runs",
        headers=headers("bob"),
        data={"message": "delegate", "session_id": "bob-conversation", "stream": "false"},
    )
    assert response.status_code == 200, response.text
    assert db.get_tasks()[1] == 0
    assert worker_model.attempts == 0


@pytest.mark.asyncio
async def test_duplicate_intake_does_not_reopen_failed_delegation(system):
    from agno.company.conversation import _conversation_scope
    from agno.company.lifecycle import _delegation
    from agno.os.authz.run_context import restore_authorization
    from agno.run.authorization import AUTHORIZATION_KEY, authorization_scope

    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    origin = next(entry["company_conversation"] for entry in task["transitions"] if "company_conversation" in entry)
    authority = restore_authorization(executor.app, _delegation(task)[AUTHORIZATION_KEY])
    context = RunContext(
        run_id=origin["run_id"], session_id=origin["session_id"], user_id="alice", authorization=authority
    )
    toolkit = next(tool for tool in host.company_manager.tools if isinstance(tool, CompanyLifecycleTools))

    async def repeat():
        with authorization_scope(lambda: authority), _conversation_scope(origin):
            return json.loads(
                await toolkit.adelegate_company_outcome(
                    "SDK",
                    "A verified version=2 artifact",
                    "Deliver artifact",
                    "Produce a checked artifact with version=2",
                    "agent",
                    "writer",
                    _agno_agent=host.company_manager,
                    _agno_run_context=context,
                )
            )

    assert (await repeat())["run_id"] == task["job_id"]
    assessor.question = True
    await execute(worker)
    assert (await repeat())["status"] == "backlog"
    assert db.get_tasks()[1] == 1
    assert db.get_task(task["id"])["status"] == "backlog"
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None


@pytest.mark.asyncio
async def test_status_and_unrelated_turns_while_worker_is_running(system):
    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    worker_model.started = asyncio.Event()
    worker_model.release = asyncio.Event()
    active = asyncio.create_task(execute(worker))
    try:
        await asyncio.wait_for(worker_model.started.wait(), 5)
        for message, expected in (("status", "in_progress"), ("unrelated", "Unrelated answer")):
            reply = await asyncio.wait_for(
                client.post(
                    "/agents/company--manager/runs",
                    headers=headers(),
                    data={"message": message, "session_id": "conversation", "stream": "false"},
                ),
                5,
            )
            assert reply.status_code == 200 and expected in reply.text, reply.text
            assert not active.done()
        assert db.get_task(task["id"])["status"] == "in_progress"
    finally:
        worker_model.release.set()
        await active
    await execute(worker)
    assert db.get_task(task["id"])["status"] == "done"


@pytest.mark.asyncio
async def test_project_assessment_failure_is_visible_and_not_repeated(system, monkeypatch):
    import agno.company.lifecycle as lifecycle

    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    original = lifecycle._assess
    assessments = 0

    async def fail_project(os, identity, prompt, evidence):
        nonlocal assessments
        if prompt["kind"] == "project":
            assessments += 1
            return lifecycle.OutcomeAssessment(decision="failed", reason="Project verification unavailable")
        return await original(os, identity, prompt, evidence)

    monkeypatch.setattr(lifecycle, "_assess", fail_project)
    await execute(worker)
    await execute(worker)
    assert db.get_task(task["id"])["status"] == "done"
    project = db.get_project(task["project_id"])
    assert project["status"] == "active"
    assert project["transitions"][-1]["system_decision"]["decision"] == "failed"
    await executor._tick()
    assert assessments == 1
    assert worker_model.attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["brief", "permission"])
async def test_changed_scope_or_permission_during_assessment_stops_decision(system, monkeypatch, change):
    import agno.company.lifecycle as lifecycle

    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    original = lifecycle._assess

    async def change_after_assessment(*args, **kwargs):
        assessment = await original(*args, **kwargs)
        if change == "brief":
            db.update_task(task["id"], brief="New scope requires new acceptance")
        else:
            auth.set_role_scopes("delegator", [scope for scope in SCOPES if scope != "tasks:write"])
        return assessment

    monkeypatch.setattr(lifecycle, "_assess", change_after_assessment)
    await execute(worker)
    current = db.get_task(task["id"])
    assert current["status"] == "in_review"
    assert not any(
        entry.get("system_decision", {}).get("operation") == "assessment" for entry in current["transitions"]
    )
    await executor._tick()
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
    assert worker_model.attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("failure", ["disabled", "directory_unavailable"])
async def test_disabled_author_cannot_resume_or_commit_assessment(system, monkeypatch, when, failure):
    from unittest.mock import AsyncMock

    import agno.company.lifecycle as lifecycle

    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    original = lifecycle._assess
    store = AsyncMock()
    store.ais_disabled.return_value = False
    executor.app.state.user_store = store
    executor.app.state.user_directory_fail_closed = True

    def deny():
        if failure == "disabled":
            store.ais_disabled.return_value = True
        else:
            store.ais_disabled.side_effect = RuntimeError("Directory unavailable")

    if when == "before":
        deny()

    async def disable_after_assessment(*args, **kwargs):
        result = await original(*args, **kwargs)
        deny()
        return result

    monkeypatch.setattr(lifecycle, "_assess", disable_after_assessment)
    # Execute the already authorized ticket without claiming a new human request.
    await execute(worker)
    current = db.get_task(task["id"])
    assert current["status"] != "done"
    assert not any(
        entry.get("system_decision", {}).get("operation") == "assessment" for entry in current["transitions"]
    )
    await executor._tick()
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["brief", "project_outcome"])
async def test_transaction_rechecks_scope_after_final_application_read(system, monkeypatch, change):
    import agno.company.lifecycle as lifecycle

    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    original = lifecycle._manager_call

    async def change_before_transition(manager, method, **kwargs):
        if method == "transition_task":
            if change == "brief":
                db.update_task(task["id"], brief="Updated after application checks")
            else:
                db.update_project(task["project_id"], outcome="Updated after application checks")
        return await original(manager, method, **kwargs)

    monkeypatch.setattr(lifecycle, "_manager_call", change_before_transition)
    await execute(worker)
    assert db.get_task(task["id"])["status"] == "in_review"
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None


def leader_context(executor, task, session_id="conversation"):
    from agno.company.lifecycle import _delegation
    from agno.os.authz.run_context import restore_authorization
    from agno.run.authorization import AUTHORIZATION_KEY

    authority = restore_authorization(executor.app, _delegation(task)[AUTHORIZATION_KEY])
    # The Super Agent leader shares the member's session and user but has its own run id.
    return RunContext(run_id="leader-" + uuid4().hex, session_id=session_id, user_id="alice", authorization=authority)


@pytest.mark.asyncio
async def test_leader_resubmit_while_running_joins_delegated_run(system):
    from agno.company.conversation import asubmit_company_task

    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    receipt = await asubmit_company_task(host, task["id"], leader_context(executor, task))
    assert receipt["run_id"] == task["job_id"]
    assert db.get_task(task["id"])["job_id"] == task["job_id"]


@pytest.mark.asyncio
async def test_leader_resubmit_after_delegated_task_finished_returns_receipt(system):
    from agno.company.conversation import asubmit_company_task

    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    await execute(worker)
    await execute(worker)
    finished = db.get_task(task["id"])
    assert finished["status"] == "done"
    receipt = await asubmit_company_task(host, task["id"], leader_context(executor, task))
    assert receipt["already_submitted"] is True
    assert receipt["run_id"] == finished["job_id"]
    assert receipt["task_status"] == "done"
    assert db.get_task(task["id"]) == finished
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
    assert worker_model.attempts == 2


@pytest.mark.asyncio
async def test_other_conversation_cannot_resubmit_finished_task(system):
    from agno.company.conversation import asubmit_company_task

    host, db, worker, executor, client, auth, assessor, worker_model = system
    task = await delegate(system)
    await execute(worker)
    await execute(worker)
    with pytest.raises(ValueError, match="Only accepted Tasks can be submitted"):
        await asubmit_company_task(host, task["id"], leader_context(executor, task, session_id="other"))
