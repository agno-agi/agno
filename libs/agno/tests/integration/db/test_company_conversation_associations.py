"""Concurrent conversation joins retain every origin across all Company SQL adapters."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from agno.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.os import AgentOS, CompanyConfig
from tests.integration.db import test_company_details
from tests.integration.db.test_company_details import call
from tests.integration.db.test_company_execution_parity import OfflineModel, accepted

db = test_company_details.db


@pytest.mark.asyncio
async def test_concurrent_associations_preserve_attempt_and_lifecycle(db):
    app = AgentOS(db=db, agents=[Agent(id="writer", model=OfflineModel(), db=db)], company=CompanyConfig()).get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task = await accepted(client)
    task = await call(db.get_task, task["id"])
    started = await call(db.start_task_run, task["id"], 1, task["transitions"])
    assert started is not None
    replicas = [type(db).from_dict(db.to_dict()) for _ in range(4)]
    origins = [
        {"session_id": "conversation-" + str(i), "run_id": "origin-" + str(i), "user_id": "alice"} for i in range(4)
    ]

    async def associate(replica, origin):
        args = (task["id"], started["job_id"], origin)
        if isinstance(replica, AsyncBaseDb):
            return await replica.associate_task_conversation(*args)
        return await asyncio.to_thread(replica.associate_task_conversation, *args)

    try:
        assert all(await asyncio.gather(*[associate(replica, origin) for replica, origin in zip(replicas, origins)]))
        assert all(await asyncio.gather(*[associate(replica, origin) for replica, origin in zip(replicas, origins)]))
        saved = await call(db.get_task, task["id"])
        event = saved["transitions"][-1]
        actual = [event["company_conversation"], *event["company_conversations"]]
        assert len(actual) == 4
        assert {origin["run_id"] for origin in actual} == {origin["run_id"] for origin in origins}
        assert len(saved["transitions"]) == len(started["transitions"])
        assert saved["status"] == "in_progress"
        assert await call(db.associate_task_conversation, task["id"], "different-attempt", origins[0]) is None
    finally:
        for replica in replicas:
            await call(replica.close)


@pytest.mark.asyncio
async def test_conversation_claim_never_reassigns_existing_owner(db):
    first = await call(db.claim_company_conversation, "shared", "alice", "super-agent")
    assert first["user_id"] == "alice"
    replicas = [type(db).from_dict(db.to_dict()) for _ in range(4)]

    async def claim(replica, owner):
        if isinstance(replica, AsyncBaseDb):
            return await replica.claim_company_conversation("new", owner, "super-agent")
        return await asyncio.to_thread(replica.claim_company_conversation, "new", owner, "super-agent")

    try:
        rows = await asyncio.gather(*[claim(replica, "user-" + str(i)) for i, replica in enumerate(replicas)])
        assert len({row["user_id"] for row in rows}) == 1
        retained = await call(db.claim_company_conversation, "shared", "bob", "different-team")
        assert retained["user_id"] == "alice" and retained["team_id"] == "super-agent"
    finally:
        for replica in replicas:
            await call(replica.close)
