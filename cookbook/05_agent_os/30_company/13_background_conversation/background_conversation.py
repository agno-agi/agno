"""Exercise responsive conversation and an accepted background Task without provider calls.

Uses a disposable PostgreSQL schema. Authentication is disabled for this local example.
"""

import asyncio
import json
import os
from uuid import uuid4

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.os.job_queue import QueueWorker, resolve_queue_store
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


class ConversationModel(Model):
    def __init__(self):
        super().__init__(id="offline-conversation", provider="test")

    def invoke(self, messages, *args, **kwargs):
        user = next(
            message.content for message in reversed(messages) if message.role == "user"
        )
        last_user = max(
            index for index, message in enumerate(messages) if message.role == "user"
        )
        tool_results = [
            message for message in messages[last_user + 1 :] if message.role == "tool"
        ]
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


async def accepted(client, kind="agent", id="writer"):
    product = (
        await client.post(
            "/company/products",
            json={"name": "SDK", "metadata": {"secret": "never-forward"}},
        )
    ).json()
    project = (
        await client.post(
            "/company/projects", json={"product_id": product["id"], "name": "Release"}
        )
    ).json()
    approval = {"target": "active", "reason": "Approved"}
    await client.post(f"/company/projects/{project['id']}/transitions", json=approval)
    task = (
        await client.post(
            "/company/tasks",
            json={
                "product_id": product["id"],
                "project_id": project["id"],
                "title": "Draft",
                "brief": "Write a draft",
                "evidence": [{"url": "https://example.com/evidence", "hash": "abc"}],
            },
        )
    ).json()
    response = await client.post(
        f"/company/tasks/{task['id']}/transitions",
        json={
            "target": "ready",
            "reason": "Approved",
            "executor_type": kind,
            "executor_id": id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def execute_one(worker):
    job = await worker.store.claim_job(
        worker.worker_id, worker.config.lock_grace_seconds
    )
    assert job is not None
    await worker._execute_claimed(job)
    assert (await worker.store.get_job(job["id"]))["status"] == "completed"


async def main():
    schema = "conversation_example_" + uuid4().hex
    db = PostgresDb(
        db_url=os.getenv(
            "DATABASE_URL", "postgresql+psycopg://agno:agno@localhost:5532/agno"
        ),
        db_schema=schema,
    )
    writer = Agent(id="writer", model=ConversationModel(), db=db, telemetry=False)
    config = QueueConfig(durable=True, db=db, max_concurrency=4)
    agent_os = AgentOS(
        id="conversation-example",
        db=db,
        agents=[writer],
        company=CompanyConfig(),
        manager=OSManager(
            model=ConversationModel(), access_docs=False, offload_tool_results=False
        ),
        queue=config,
        telemetry=False,
    )
    app = agent_os.get_app()
    components = {"writer": writer, "super-agent": agent_os.manager}
    # Drive durable claims explicitly so this deterministic example can hold a worker open.
    # A normal AgentOS server starts its configured queue worker in the application lifespan.
    worker = QueueWorker(
        resolve_queue_store(config, db),
        lambda kind, id, scope=None: components.get(id),
        config,
        authorization_app=app,
    )
    worker._company_db = db
    app.state.queue_worker = worker
    started, release = asyncio.Event(), asyncio.Event()
    original = writer.model.ainvoke

    async def slow(*args, **kwargs):
        started.set()
        await release.wait()
        return await original(*args, **kwargs)

    writer.model.ainvoke = slow
    running = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://example"
        ) as client:
            task = await accepted(client)
            path = "/company/conversations/example"
            receipt = await client.post(
                path + "/messages",
                json={"message": "submit:" + task["id"]},
                headers={"Idempotency-Key": "request-1"},
            )
            assert receipt.status_code == 202, receipt.text
            print(receipt.json())
            await execute_one(worker)
            saved = db.get_task(task["id"])
            assert saved["status"] == "in_progress" and saved["session_id"] != "example"
            job = await worker.store.claim_job(
                worker.worker_id, config.lock_grace_seconds
            )
            running = asyncio.create_task(worker._execute_claimed(job))
            await asyncio.wait_for(started.wait(), 5)
            for message in ["status", "Hello"]:
                response = await client.post(
                    path + "/messages", json={"message": message}
                )
                assert response.status_code == 202
                await execute_one(worker)
            assert not running.done()
            tasks = await client.get(path + "/tasks")
            assert tasks.json()[0]["task_id"] == task["id"]
            print(
                "Status and unrelated conversation completed while the Task worker waited."
            )
            release.set()
            await asyncio.wait_for(running, 10)
            assert db.get_task(task["id"])["status"] == "in_review"
            print(
                "Background Task completed and retained its originating conversation."
            )
    finally:
        release.set()
        if running is not None:
            await running
        with db.db_engine.begin() as connection:
            connection.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
