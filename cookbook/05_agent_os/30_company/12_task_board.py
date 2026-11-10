"""Start a Backlog Task directly and read the board by status without a model call.

Prerequisites: Install agno, sqlalchemy, psycopg, fastapi and httpx; start PostgreSQL.
Run: .venv/bin/python cookbook/05_agent_os/30_company/12_task_board.py
Try: Set COMPANY_DB=postgres for PostgreSQL records and runs.
"""

import json
import os
import time
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.job_queue import QueueConfig
from agno.os import AgentOS, CompanyConfig
from agno.registry import Registry
from agno.workflow import Step, StepInput, StepOutput, Workflow
from fastapi.testclient import TestClient
from sqlalchemy import text


def draft(step_input: StepInput) -> StepOutput:
    context = json.loads(step_input.input)
    return StepOutput(content="Draft ready for review: " + context["brief"])


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        schema = "company_cookbook_" + uuid4().hex
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
            db=db,
            registry=Registry(workflows=[workflow]),
            company=CompanyConfig(),
            queue=QueueConfig(durable=True, db=queue_db, poll_interval=0.1),
            telemetry=False,
        )
        try:
            with TestClient(agent_os.get_app()) as client:
                product = client.post("/company/products", json={"name": "SDK"}).json()
                project = client.post(
                    "/company/projects",
                    json={"product_id": product["id"], "name": "Release"},
                ).json()
                tasks = [
                    client.post(
                        "/company/tasks",
                        json={
                            "product_id": product["id"],
                            "project_id": project["id"],
                            "title": title,
                            "brief": "Summarize reviewed changes",
                            "evidence": [{"reference": "Reviewed release changes"}],
                        },
                    ).json()
                    for title in ("Draft release notes", "Update guide", "Old draft")
                ]
                path = "/company/tasks/" + tasks[0]["id"]
                moves = {
                    option["target"]: option
                    for option in tasks[0]["allowed_transitions"]
                }
                # From Backlog, a start is allowed; the request names the executor.
                assert moves["in_progress"]["allowed"]
                assert moves["in_progress"]["starts_run"]

                executor = {"executor_type": "workflow", "executor_id": "draft"}
                started = client.post(path + "/runs", json=executor)
                assert started.status_code == 202, started.text
                repeated = client.post(path + "/runs", json=executor)
                assert repeated.json()["run_id"] == started.json()["run_id"]
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    task = client.get(path).json()
                    if task["status"] == "in_review":
                        break
                    time.sleep(0.1)
                assert task["status"] == "in_review", task
                assert task["last_run"]["status"] == "COMPLETED"
                # Once the run has finished, the same start does not begin a revision.
                late = client.post(path + "/runs", json=executor)
                assert late.status_code == 409, late.text

                client.post(
                    "/company/tasks/" + tasks[2]["id"] + "/transitions",
                    json={"target": "cancelled", "reason": "Superseded"},
                ).raise_for_status()
                # Each board column is its own filtered, paged list.
                counts = {
                    status: client.get(
                        "/company/tasks",
                        params={"project_id": project["id"], "status": status},
                    ).json()["meta"]["total_count"]
                    for status in (
                        "backlog",
                        "ready",
                        "in_progress",
                        "in_review",
                        "done",
                        "cancelled",
                    )
                }
                print("Backlog Task started directly and awaits review")
                print(json.dumps(counts, indent=2))
                print("Repeat after review was refused; no model call was made")
        finally:
            if db is not queue_db:
                db.close()
            with queue_db.db_engine.begin() as connection:
                connection.execute(
                    text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                )
            queue_db.close()
