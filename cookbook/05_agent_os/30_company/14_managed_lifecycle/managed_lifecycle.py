"""Exercise automatic lifecycle management with real PostgreSQL and offline models.

DATABASE_URL must point to a disposable PostgreSQL database. This creates and
removes a unique schema, writes checked local artifacts, and makes no model calls.
"""

import asyncio
import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.agent import Agent
from agno.company.routines import _CompanyScheduleExecutor
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, CompanyConfig
from agno.os.job_queue import QueueWorker, resolve_queue_store
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


class OfflineModel(Model):
    def __init__(self, kind="coordinator"):
        super().__init__(id="offline-lifecycle", provider="test")
        self.kind = kind
        self.attempts = 0
        self.always_revise = False
        self.bad_evidence = False
        self.question = False

    def invoke(self, messages, **kwargs):
        content = next(
            str(message.content)
            for message in reversed(messages)
            if message.role == "user"
        )
        if self.kind == "assessor":
            payload = json.loads(content)
            evidence = payload["evidence"]
            done = (
                self.bad_evidence
                or payload["kind"] == "project"
                or ("version=2" in json.dumps(evidence) and not self.always_revise)
            )
            result = {
                "decision": "question"
                if self.question
                else "done"
                if done
                else "revise",
                "reason": "The checked artifact satisfies the outcome"
                if done
                else "The artifact needs version 2",
                "evidence": ["invented"] if self.bad_evidence else list(evidence),
                "next_instruction": None if done else "Produce and verify version=2",
            }
            return ModelResponse(
                role="assistant",
                content=json.dumps(result),
                response_usage=MessageMetrics(),
            )
        if self.kind == "worker":
            last_user = max(
                i for i, message in enumerate(messages) if message.role == "user"
            )
            results = [
                message.content
                for message in messages[last_user + 1 :]
                if message.role == "tool"
            ]
            if results:
                return ModelResponse(
                    role="assistant",
                    content=str(results[-1]),
                    response_usage=MessageMetrics(),
                )
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
        last_user = max(
            i for i, message in enumerate(messages) if message.role == "user"
        )
        if (
            any(message.role == "tool" for message in messages[last_user + 1 :])
            or content != "delegate"
        ):
            return ModelResponse(
                role="assistant",
                content="Receipt recorded"
                if content == "delegate"
                else "Unrelated answer",
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


async def main():
    schema = "lifecycle_example_" + uuid4().hex
    db = PostgresDb(db_url=os.environ["DATABASE_URL"], db_schema=schema)
    with TemporaryDirectory() as directory:

        def write_and_verify_artifact(version: int) -> str:
            """Write the artifact and read its contents and checksum back."""
            path = Path(directory) / "artifact.txt"
            path.write_text(f"version={version}")
            return json.dumps(
                {
                    "artifact": str(path),
                    "content": path.read_text(),
                    "verified_sha256": sha256(path.read_bytes()).hexdigest(),
                }
            )

        worker_model = OfflineModel("worker")
        writer = Agent(
            id="writer",
            model=worker_model,
            db=db,
            tools=[write_and_verify_artifact],
            telemetry=False,
        )
        config = QueueConfig(durable=True, db=db)
        host = AgentOS(
            id="managed-lifecycle",
            db=db,
            agents=[writer],
            company=CompanyConfig(model=OfflineModel(), max_task_attempts=3),
            queue=config,
            scheduler=True,
            telemetry=False,
        )
        # Replace the reusable assessment model with an offline fixture too.
        # A deployed application uses CompanyConfig.model for both managers.
        host._company_assessor.model = OfflineModel("assessor")
        app = host.get_app()
        worker = QueueWorker(
            resolve_queue_store(config, db),
            lambda kind, component_id, scope=None: (
                writer if component_id == "writer" else None
            ),
            config,
            authorization_app=app,
        )
        worker._company_db = db
        worker._company_schedule_db = db
        app.state.queue_worker = worker
        app.state.scheduler_executor = _CompanyScheduleExecutor(
            host,
            app,
            company_db=db,
            schedule_db=db,
            base_url="http://example",
            internal_service_token=host._internal_service_token,
        )
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://example"
            ) as client:
                response = await client.post(
                    "/agents/company-manager/runs",
                    data={
                        "message": "delegate",
                        "session_id": "conversation",
                        "user_id": "alice",
                        "stream": "false",
                    },
                )
                assert response.status_code == 200, response.text
                task = db.get_tasks()[0][0]
                assert task["status"] == "in_progress"
                reply = await client.post(
                    "/agents/company-manager/runs",
                    data={
                        "message": "unrelated",
                        "session_id": "conversation",
                        "user_id": "alice",
                        "stream": "false",
                    },
                )
                assert "Unrelated answer" in reply.text
                # Drive the real durable queue deterministically, instead of waiting
                # for its background polling interval in this offline demonstration.
                for _ in range(2):
                    job = await worker.store.claim_job(
                        worker.worker_id, worker.config.lock_grace_seconds
                    )
                    assert job is not None
                    await worker._execute_claimed(job)
                finished = db.get_task(task["id"])
                assert finished["status"] == "done"
                assert finished["session_id"] == task["session_id"]
                assert db.get_project(task["project_id"])["status"] == "done"
                assert worker_model.attempts == 2
                print(
                    json.dumps(
                        {
                            "task_id": task["id"],
                            "status": finished["status"],
                            "attempts": worker_model.attempts,
                        }
                    )
                )
                print(
                    "One checked revision; Task and Project completed without lifecycle approvals"
                )
        finally:
            with db.db_engine.begin() as conn:
                conn.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
            db.close()


if __name__ == "__main__":
    asyncio.run(main())
