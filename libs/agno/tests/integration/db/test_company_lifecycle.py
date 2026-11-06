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
from agno.company.lifecycle import CompanyLifecycleTools, _advance_task
from agno.company.routines import _CompanyScheduleExecutor
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, Authorization, CompanyConfig
from agno.os.job_queue import QueueWorker, resolve_queue_store
from agno.run import RunContext
from agno.run.authorization import authorization_scope

SECRET = "company-managed-lifecycle-test-secret-32-bytes"
SCOPES = [
    "agents:company-manager:run",
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

    def invoke(self, messages, **kwargs):
        content = next(str(message.content) for message in reversed(messages) if message.role == "user")
        if self.kind == "assessor":
            payload = json.loads(content)
            evidence = payload["evidence"]
            done = payload["kind"] == "project" or ("version=2" in json.dumps(evidence) and not self.always_revise)
            result = {
                "decision": "done" if done else "revise",
                "reason": "The checked artifact satisfies the outcome" if done else "The artifact needs version 2",
                "evidence": ["invented"] if self.bad_evidence else list(evidence),
                "next_instruction": None if done else "Produce and verify version=2",
            }
            return ModelResponse(role="assistant", content=json.dumps(result), response_usage=MessageMetrics())
        if self.kind == "worker":
            self.attempts += 1
            return ModelResponse(
                role="assistant",
                content="checked artifact version=" + ("2" if '"revision"' in content else "1"),
                response_usage=MessageMetrics(),
            )
        last_user = max(i for i, message in enumerate(messages) if message.role == "user")
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
async def system():
    schema = "managed_lifecycle_" + uuid4().hex
    url = os.environ.get("COMPANY_TEST_DB_URL", "postgresql+psycopg://agno:agno@127.0.0.1:5532/agno")
    db = PostgresDb(db_url=url, db_schema=schema)
    worker_model = OfflineModel("worker")
    writer = Agent(id="writer", db=db, model=worker_model, telemetry=False)
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
    job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert job is not None
    await worker._execute_claimed(job)
    return await worker.store.get_job(job["id"])


async def delegate(system):
    host, db, worker, executor, client, auth, assessor, worker_model = system
    response = await client.post(
        "/agents/company-manager/runs",
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
        "/agents/company-manager/runs",
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
    assert db.get_project(task["project_id"])["status"] == "done"
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
