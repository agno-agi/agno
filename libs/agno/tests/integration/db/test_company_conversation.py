"""Actual API and PostgreSQL queue conversation dispatch, without provider calls."""

import asyncio
import json
import os
import time
from uuid import uuid4

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from agno.agent import Agent
from agno.company.conversation import _conversation_run_id
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, Authorization, CompanyConfig, OSManager
from agno.os.job_queue import QueueWorker, resolve_queue_store
from agno.registry._reserved import MANAGER_TEAM_ID
from tests.integration.db.test_company_execution_parity import accepted


class ConversationModel(Model):
    def __init__(self):
        super().__init__(id="offline-conversation", provider="test")

    def invoke(self, messages, *args, **kwargs):
        user = next(message.content for message in reversed(messages) if message.role == "user")
        last_user = max(index for index, message in enumerate(messages) if message.role == "user")
        tool_results = [message for message in messages[last_user + 1 :] if message.role == "tool"]
        tool = None
        if str(user).startswith("submit:") and not tool_results:
            tool = ("submit_accepted_task", {"task_id": str(user).split(":", 1)[1]})
        elif user == "status" and not tool_results:
            tool = ("get_submitted_tasks", {})
        if tool:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": tool[0], "arguments": json.dumps(tool[1])},
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(
            role="assistant",
            content=str(tool_results[-1].content) if tool_results else "Hello",
            response_usage=MessageMetrics(),
        )

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


SECRET = "company-conversation-offline-key-32-characters"


def headers(user="alice", scopes=None):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": user,
                "aud": "conversation-test",
                "scopes": scopes if scopes is not None else ["agent_os:admin"],
                "exp": time.time() + 600,
            },
            SECRET,
            algorithm="HS256",
        )
    }


@pytest_asyncio.fixture(params=[False, True])
async def system(request):
    schema = "conversation_" + uuid4().hex
    db = PostgresDb(
        db_url=os.getenv("COMPANY_TEST_DB_URL", "postgresql+psycopg://agno:agno@localhost:5532/agno"), db_schema=schema
    )
    worker_agent = Agent(id="writer", model=ConversationModel(), db=db, telemetry=False)
    manager_model = ConversationModel()
    queue_config = QueueConfig(durable=True, db=db, queue_per_session=False, max_concurrency=4)
    auth = (
        Authorization(verification_keys=[SECRET], algorithm="HS256", audience="conversation-test")
        if request.param
        else False
    )
    if request.param == "managed":
        auth.define_role("caller", ["agent_os:admin"]).assign("alice", "caller").assign("owner", "caller")
    agent_os = AgentOS(
        id="conversation-test",
        authorization=auth,
        user_isolation=True,
        user_directory=True if request.param else False,
        db=db,
        agents=[worker_agent],
        company=CompanyConfig(),
        manager=OSManager(model=manager_model, access_docs=False, offload_tool_results=False),
        queue=queue_config,
        telemetry=False,
    )
    agent_os._test_authorization = auth
    app = agent_os.get_app()
    components = {"writer": worker_agent, MANAGER_TEAM_ID: agent_os.manager}
    worker = QueueWorker(
        resolve_queue_store(queue_config, db),
        lambda kind, component_id, scope=None: components.get(component_id),
        queue_config,
        authorization_app=app,
    )
    worker._company_db = db
    app.state.queue_worker = worker
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers() if request.param else {}
    ) as client:
        yield client, db, worker, agent_os, components
    with db.db_engine.begin() as conn:
        conn.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
    db.close()


async def execute_one(worker):
    job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert job is not None
    await worker._execute_claimed(job)
    return await worker.store.get_job(job["id"])


@pytest.mark.asyncio
async def test_conversation_dispatch_returns_before_worker_and_persists_origin(system):
    client, db, worker, _, components = system
    task = await accepted(client)
    path = "/company/conversations/conversation-one"
    receipt = await client.post(
        path + "/messages", json={"message": "submit:" + task["id"]}, headers={"Idempotency-Key": "first"}
    )
    assert receipt.status_code == 202, receipt.text
    assert receipt.json()["status"] == "PENDING"
    first = await execute_one(worker)
    assert first["status"] == "completed", first
    saved = db.get_task(task["id"])
    assert saved["status"] == "in_progress", db.get_run(first["id"], deserialize=False)
    assert saved["session_id"] != "conversation-one"
    assert saved["transitions"][-1]["company_conversation"]["run_id"] == receipt.json()["run_id"]
    assert (
        await client.post(
            path + "/messages", json={"message": "submit:" + task["id"]}, headers={"Idempotency-Key": "first"}
        )
    ).json()["run_id"] == receipt.json()["run_id"]
    started, release = asyncio.Event(), asyncio.Event()
    original = components["writer"].model.ainvoke

    async def slow(*args, **kwargs):
        started.set()
        await release.wait()
        return await original(*args, **kwargs)

    components["writer"].model.ainvoke = slow
    pending = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    running = asyncio.create_task(worker._execute_claimed(pending))
    await asyncio.wait_for(started.wait(), 5)
    try:
        status = await client.post(path + "/messages", json={"message": "status"})
        assert status.status_code == 202
        assert (await execute_one(worker))["status"] == "completed"
        unrelated = await client.post(path + "/messages", json={"message": "Hi"})
        assert unrelated.status_code == 202
        assert (await execute_one(worker))["status"] == "completed"
        assert not running.done()
        statuses = await client.get(path + "/tasks", params={"origin_run_id": receipt.json()["run_id"]})
        assert statuses.json()[0]["task_id"] == task["id"]
        assert (await client.get(path + "/tasks", params={"origin_run_id": unrelated.json()["run_id"]})).json() == []
    finally:
        release.set()
        await asyncio.wait_for(running, 10)
    assert db.get_task(task["id"])["status"] == "in_review"


@pytest.mark.asyncio
async def test_conversation_turns_serialize_and_trusted_receipt_survives_retention(system):
    client, db, worker, _, _ = system
    path = "/company/conversations/serial/messages"
    stable = str(uuid4())
    token = _conversation_run_id.set(stable)
    try:
        response = await client.post(path, json={"message": "hello"})
    finally:
        _conversation_run_id.reset(token)
    assert response.status_code == 202, response.text
    assert response.json()["run_id"] == stable
    second = await client.post(path, json={"message": "second"})
    assert second.status_code == 202
    first_job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert first_job["payload"]["serialize_session"] is True
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
    await worker._execute_claimed(first_job)
    assert (await execute_one(worker))["id"] == second.json()["run_id"]
    table = db._get_table("jobs")
    with db.Session() as session, session.begin():
        session.execute(table.delete().where(table.c.id == stable))
    token = _conversation_run_id.set(stable)
    try:
        repeated = await client.post(path, json={"message": "hello"})
    finally:
        _conversation_run_id.reset(token)
    assert repeated.json()["status"] == "COMPLETED", repeated.text
    assert await worker.store.get_job(stable) is None


@pytest.mark.asyncio
async def test_submission_authorization_and_conversation_isolation(system):
    client, db, worker, agent_os, _ = system
    if not agent_os.authorization:
        pytest.skip("Authorization-specific case")
    task = await accepted(client)
    path = "/company/conversations/owned"
    denied = await client.post(path + "/messages", json={"message": "hello"}, headers=headers(scopes=[]))
    assert denied.status_code == 403
    # Permission to converse is not permission to run a worker or read its Task.
    receipt = await client.post(
        path + "/messages", json={"message": "submit:" + task["id"]}, headers=headers(scopes=["teams:super-agent:run"])
    )
    assert receipt.status_code == 202, receipt.text
    await execute_one(worker)
    assert db.get_task(task["id"])["status"] == "ready"
    assert (
        await client.post(path + "/messages", json={"message": "hello"}, headers=headers(user="bob"))
    ).status_code == 403
    assert (await client.get(path + "/tasks", headers=headers(user="bob"))).json() == []


@pytest.mark.asyncio
async def test_restart_retains_associations_and_duplicate_submission(system):
    from agno.company.conversation import asubmit_company_task
    from agno.run import RunContext

    client, db, worker, agent_os, _ = system
    if agent_os.authorization:
        pytest.skip("Trusted direct helper counterpart covered separately from HTTP authorization")
    task = await accepted(client)
    context = RunContext(run_id="origin", session_id="discussion", user_id=None)
    first = await asubmit_company_task(agent_os, task["id"], context)
    second = await asubmit_company_task(agent_os, task["id"], context)
    assert first["run_id"] == second["run_id"]
    # A newly constructed store reads association from the Task transition, not process memory.
    replica = PostgresDb.from_dict(db.to_dict())
    try:
        saved = replica.get_task(task["id"])
        assert saved["transitions"][-1]["company_conversation"]["run_id"] == "origin"
        assert saved["session_id"] != "discussion"
    finally:
        replica.close()
    assert (await execute_one(worker))["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("system", ["managed"], indirect=True)
async def test_managed_caller_is_preserved_and_revocation_stops_worker(system):
    client, db, worker, agent_os, components = system
    task = await accepted(client)
    receipt = await client.post("/company/conversations/managed/messages", json={"message": "submit:" + task["id"]})
    assert receipt.status_code == 202, receipt.text
    assert (await execute_one(worker))["status"] == "completed"
    saved = db.get_task(task["id"])
    assert saved["status"] == "in_progress", db.get_run(receipt.json()["run_id"], deserialize=False)
    assert saved["transitions"][-1]["started_by"] == "alice"
    agent_os._test_authorization.unassign("alice", "caller")
    ran = []
    original = components["writer"].model.ainvoke

    async def record(*args, **kwargs):
        ran.append(True)
        return await original(*args, **kwargs)

    components["writer"].model.ainvoke = record
    assert (await execute_one(worker))["status"] == "failed"
    assert ran == []


@pytest.mark.asyncio
async def test_committed_ticket_recovers_conversation_after_projection_failure(system, monkeypatch):
    client, db, worker, _, _ = system
    task = await accepted(client)
    response = await client.post("/company/conversations/recover/messages", json={"message": "submit:" + task["id"]})
    assert response.status_code == 202
    with monkeypatch.context() as outage:

        def unavailable(*args, **kwargs):
            raise RuntimeError("Task projection temporarily unavailable")

        outage.setattr(db, "start_task_run", unavailable)
        await execute_one(worker)
    assert db.get_task(task["id"])["status"] == "ready"
    # A fresh queue worker restores origin from the committed ticket before reserving execution.
    restarted = QueueWorker(
        worker.store, worker.resolve_component, worker.config, authorization_app=worker.authorization_app
    )
    restarted._company_db = db
    assert (await execute_one(restarted))["status"] == "completed"
    task = db.get_task(task["id"])
    assert task["status"] == "in_review"
    start = next(event for event in task["transitions"] if event.get("company_conversation"))
    assert start["company_conversation"]["run_id"] == response.json()["run_id"]


@pytest.mark.asyncio
async def test_concurrent_conversations_join_direct_submission_without_losing_origins(system):
    client, db, worker, _, _ = system
    task = await accepted(client)
    direct = await client.post("/company/tasks/" + task["id"] + "/runs", json={})
    assert direct.status_code == 202, direct.text
    held = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert held["id"] == direct.json()["run_id"]
    receipts = await asyncio.gather(
        *[
            client.post("/company/conversations/" + name + "/messages", json={"message": "submit:" + task["id"]})
            for name in ["first-join", "second-join"]
        ]
    )
    assert all(response.status_code == 202 for response in receipts)
    assert all(job["status"] == "completed" for job in await asyncio.gather(execute_one(worker), execute_one(worker)))
    for name, receipt in zip(["first-join", "second-join"], receipts):
        result = await client.get(
            "/company/conversations/" + name + "/tasks", params={"origin_run_id": receipt.json()["run_id"]}
        )
        assert result.status_code == 200
        assert result.json()[0]["run_id"] == direct.json()["run_id"]
    replica = PostgresDb.from_dict(db.to_dict())
    try:
        event = replica.get_task(task["id"])["transitions"][-1]
        origins = [event["company_conversation"], *event["company_conversations"]]
        assert {origin["session_id"] for origin in origins} == {"first-join", "second-join"}
    finally:
        replica.close()
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
    await worker._execute_claimed(held)
    assert db.get_task(task["id"])["status"] == "in_review"


@pytest.mark.asyncio
async def test_first_message_atomically_claims_conversation_owner(system):
    client, db, worker, agent_os, _ = system
    if not agent_os.authorization:
        pytest.skip("Verified ownership requires authentication")
    # Initialize ordinary run tables before racing the first request to this session.
    warm = await client.post("/company/conversations/warm/messages", json={"message": "Hello"})
    assert warm.status_code == 202
    await execute_one(worker)
    responses = await asyncio.gather(
        *[
            client.post(
                "/company/conversations/shared-new/messages", json={"message": "Hello"}, headers=headers(user=user)
            )
            for user in ["alice", "bob"]
        ]
    )
    assert sorted(response.status_code for response in responses) == [202, 403]
    owner = db.get_session("shared-new", deserialize=False)["user_id"]
    assert responses[["alice", "bob"].index(owner)].status_code == 202
    assert (await execute_one(worker))["status"] == "completed"
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("system", ["managed"], indirect=True)
@pytest.mark.parametrize("revoke", ["role", "disabled", "owner", "component"])
async def test_queued_coordinator_rechecks_authority_and_session(system, revoke):
    client, db, worker, agent_os, _ = system
    receipt = await client.post("/company/conversations/revoked/messages", json={"message": "Hello"})
    assert receipt.status_code == 202, receipt.text
    if revoke == "role":
        agent_os._test_authorization.unassign("alice", "caller")
    elif revoke == "disabled":
        await agent_os.user_directory.aset_disabled("alice", True)
    else:
        session = db.get_session("revoked")
        if revoke == "owner":
            table = db._get_table(table_type="sessions")
            with db.Session() as transaction, transaction.begin():
                transaction.execute(table.update().where(table.c.session_id == "revoked").values(user_id="bob"))
        else:
            session.team_id = "different-team"
            db.upsert_session(session)
    ran = []
    original = agent_os.manager.model.ainvoke

    async def record(*args, **kwargs):
        ran.append(True)
        return await original(*args, **kwargs)

    agent_os.manager.model.ainvoke = record
    assert (await execute_one(worker))["status"] == "failed"
    assert ran == []


@pytest.mark.asyncio
async def test_unassigned_task_session_cannot_be_used_as_conversation(system):
    from uuid import NAMESPACE_URL, uuid5

    client, db, worker, _, _ = system
    task = await accepted(client)
    table = db._get_table(table_type="tasks")
    with db.Session() as session, session.begin():
        session.execute(table.update().where(table.c.id == task["id"]).values(session_id=None))
    assert db.get_task(task["id"])["session_id"] is None
    collision = str(uuid5(NAMESPACE_URL, "agno:company:task:" + task["id"]))
    receipt = await client.post(
        "/company/conversations/" + collision + "/messages", json={"message": "submit:" + task["id"]}
    )
    assert receipt.status_code == 202
    await execute_one(worker)
    assert db.get_task(task["id"])["status"] == "ready"
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
