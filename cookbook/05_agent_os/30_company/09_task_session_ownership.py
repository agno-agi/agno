"""Two collaborators revise one Task through its owner's durable session.

Run with PostgreSQL on localhost:5532. Set COMPANY_DB=postgres for PostgreSQL
Company and run storage; the default uses temporary SQLite plus a PostgreSQL queue.
This example uses a local workflow and makes no model calls.
"""

import json
import os
import time
from tempfile import TemporaryDirectory
from uuid import uuid4

import jwt
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.job_queue import QueueConfig
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from agno.workflow import Step, StepOutput, Workflow
from fastapi.testclient import TestClient
from sqlalchemy import text


def draft(step_input):
    return StepOutput(
        content="Reviewed draft: " + json.loads(step_input.input)["brief"]
    )


def wait_for_review(client, path):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        task = client.get(path).json()
        if task["status"] == "in_review":
            return task
        time.sleep(0.1)
    raise RuntimeError("Task did not reach review before the deadline")


if __name__ == "__main__":
    secret = "local-cookbook-only-secret-at-least-32-bytes"
    scopes = [
        "products:read",
        "products:write",
        "projects:read",
        "projects:write",
        "tasks:read",
        "tasks:write",
        "wiki:read",
        "workflows:run",
    ]

    def headers(user):
        token = jwt.encode(
            {
                "sub": user,
                "aud": "task-ownership",
                "scopes": scopes,
                "exp": int(time.time()) + 3600,
            },
            secret,
            algorithm="HS256",
        )
        return {"Authorization": "Bearer " + token}

    with TemporaryDirectory() as directory:
        schema = "company_ownership_" + uuid4().hex
        queue_db = PostgresDb(
            db_url=os.getenv(
                "COMPANY_QUEUE_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
            ),
            db_schema=schema,
        )
        db = (
            queue_db
            if os.getenv("COMPANY_DB") == "postgres"
            else SqliteDb(db_file=directory + "/company.db")
        )
        workflow = Workflow(
            id="draft",
            db=db,
            steps=[Step(name="Draft", executor=draft)],
            telemetry=False,
        )
        agent_os = AgentOS(
            id="task-ownership",
            db=db,
            workflows=[workflow],
            company=CompanyConfig(automation_history_retention_days=30),
            authorization=Authorization(verification_keys=[secret], algorithm="HS256"),
            user_isolation=True,
            queue=QueueConfig(durable=True, db=queue_db, poll_interval=0.1),
            telemetry=False,
        )
        try:
            with TestClient(agent_os.get_app(), headers=headers("alice")) as client:
                product = client.post("/company/products", json={"name": "SDK"}).json()
                project = client.post(
                    "/company/projects",
                    json={"product_id": product["id"], "name": "Release"},
                ).json()
                task = client.post(
                    "/company/tasks",
                    json={
                        "product_id": product["id"],
                        "project_id": project["id"],
                        "title": "Release notes",
                        "brief": "Summarize reviewed changes",
                    },
                ).json()
                path = "/company/tasks/" + task["id"]
                client.post(
                    path + "/transitions",
                    json={
                        "target": "ready",
                        "reason": "Scope agreed",
                        "executor_type": "workflow",
                        "executor_id": "draft",
                    },
                ).raise_for_status()
                first = client.post(path + "/runs")
                first.raise_for_status()
                wait_for_review(client, path)
                second = client.post(
                    path + "/runs", json={"attempt": 2}, headers=headers("bob")
                )
                second.raise_for_status()
                task = wait_for_review(client, path)
                assert first.json()["session_id"] == second.json()["session_id"]
                assert task["user_id"] == "alice"
                starts = [
                    entry for entry in task["transitions"] if entry.get("attempt")
                ]
                assert [entry["started_by"] for entry in starts] == ["alice", "bob"]
                runs = client.get(path + "/runs").json()["data"]
                assert len(runs) == 2 and all(run["user_id"] == "alice" for run in runs)
                print("Alice and Bob started two attempts in Alice's Task session.")
                print("Both results are durable; the Task awaits human review.")
        finally:
            if db is not queue_db:
                db.close()
            with queue_db.db_engine.begin() as connection:
                connection.execute(
                    text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                )
            queue_db.close()
