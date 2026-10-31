"""Execute an accepted Task through the durable queue without a model call.

Prerequisites: Install agno, sqlalchemy, psycopg, fastapi and httpx; start PostgreSQL.
Run: .venv/bin/python cookbook/05_agent_os/30_company/06_execute_tasks.py
Try: Set COMPANY_DB=postgres for PostgreSQL records and runs. Set
COMPANY_AUTOMATION=1 for scheduler pickup and bounded Routine acceptance.
"""

import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.company import CompanyManager
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
    assert set(context) == {"brief", "wiki", "evidence", "execution_context"}
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
        automatic = os.getenv("COMPANY_AUTOMATION") == "1"
        agent_os = AgentOS(
            db=db,
            registry=Registry(workflows=[workflow]),
            company=CompanyConfig(),
            queue=QueueConfig(durable=True, db=queue_db, poll_interval=0.1),
            telemetry=False,
            scheduler=automatic,
            scheduler_poll_interval=0.1,
        )
        try:
            with TestClient(agent_os.get_app()) as client:
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
                        "title": "Draft release notes",
                        "brief": "Summarize reviewed changes",
                        "evidence": [{"reference": "Reviewed release changes"}],
                    },
                ).json()
                path = "/company/tasks/" + task["id"]
                accepted = client.post(
                    path + "/transitions",
                    json={
                        "target": "ready",
                        "reason": "Scope agreed",
                        "executor_type": "workflow",
                        "executor_id": "draft",
                    },
                )
                assert accepted.status_code == 200, accepted.text
                if automatic:
                    # Advance the existing schedule for a fast demonstration;
                    # normal deployments leave its configured cron untouched.
                    schedule = db.get_schedule_by_name("Company automation")
                    db.update_schedule(schedule["id"], next_run_at=0)
                else:
                    started = client.post(path + "/runs", json={"attempt": 1})
                    assert started.status_code == 202, started.text
                    duplicate = client.post(path + "/runs", json={"attempt": 1})
                    assert duplicate.json()["run_id"] == started.json()["run_id"]
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    task = client.get(path).json()
                    if task["status"] == "in_review":
                        break
                    time.sleep(0.1)
                assert task["status"] == "in_review", task
                assert task["result"]["status"] == "COMPLETED"
                history = client.get(
                    path + "/runs", params={"limit": 10, "page": 1}
                ).json()
                assert history["meta"]["total_count"] == 1
                attention = client.get(
                    "/company/attention", params={"product_id": product["id"]}
                ).json()
                print("Task completed and awaits review")
                print(json.dumps(attention, indent=2))
                if automatic:
                    release = Path(directory) / "release.md"
                    release.write_text("# Release\nDocument the reviewed API.\n")
                    source = client.post(
                        "/company/sources",
                        json={
                            "product_id": product["id"],
                            "type": "markdown",
                            "reference": str(release),
                        },
                    ).json()
                    routine = client.post(
                        "/company/routines",
                        json={
                            "product_id": product["id"],
                            "name": "intake",
                            "template": "intake",
                            "executor_type": "workflow",
                            "executor_id": "draft",
                            "cron_expr": "0 0 1 1 *",
                            "auto_accept": {
                                "executor_type": "workflow",
                                "executor_id": "draft",
                                "source_ids": [source["id"]],
                                "required_checks": [
                                    "has_source_evidence",
                                    "executor_registered",
                                ],
                                "limits": {
                                    "max_acceptances": 1,
                                    "expires_at": int(time.time()) + 3600,
                                },
                            },
                        },
                    )
                    routine.raise_for_status()
                    manager = CompanyManager(db, agent_os.registry)
                    project = manager.create_project(
                        product_id=product["id"], name="Release guide"
                    )
                    manager.transition_project(
                        project_id=project["id"], target="active", reason="Scope agreed"
                    )
                    evidence = manager.read_source(source["id"], "cookbook-source-scan")
                    proposal = manager.intake(
                        source_id=source["id"],
                        run_id="cookbook-source-scan",
                        proposal={
                            "title": "Document the reviewed API",
                            "brief": "Explain the released API in the guide",
                            "proposal_key": "reviewed-api-guide",
                            "evidence_links": [item["link"] for item in evidence],
                            "evidence_hashes": {
                                item["link"]: item["content_hash"] for item in evidence
                            },
                        },
                        routine_id=routine.json()["id"],
                        project_id=project["id"],
                        executor_type="workflow",
                        executor_id="draft",
                    )
                    assert proposal["status"] == "backlog"
                    db.update_schedule(schedule["id"], next_run_at=0)
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        proposal = manager.get_task(proposal["id"])
                        if proposal["status"] == "in_review":
                            break
                        time.sleep(0.1)
                    assert proposal["status"] == "in_review", proposal
                    client.patch(
                        "/company/routines/" + routine.json()["id"],
                        json={"auto_accept": False},
                    ).raise_for_status()
                    print(
                        "Scheduler picked up Ready work and accepted one verified Routine proposal."
                    )
                    # A human reviews the Task. Refresh can only propose Project
                    # completion; a separate human policy grants the tick permission.
                    manager.transition_task(
                        task_id=proposal["id"],
                        target="done",
                        reason="Human reviewed the guide",
                    )
                    refresh = client.post(
                        "/company/routines",
                        json={
                            "product_id": product["id"],
                            "name": "refresh",
                            "template": "refresh",
                            "executor_type": "workflow",
                            "executor_id": "draft",
                            "cron_expr": "0 0 1 1 *",
                            "auto_accept": {
                                "executor_type": "workflow",
                                "executor_id": "draft",
                                "complete_projects": True,
                                "work_scope": {"project_ids": [project["id"]]},
                                "required_checks": [
                                    "project_active",
                                    "executor_registered",
                                ],
                                "limits": {
                                    "max_acceptances": 1,
                                    "expires_at": int(time.time()) + 3600,
                                },
                            },
                        },
                    )
                    refresh.raise_for_status()
                    assert manager.refresh(product["id"])["completion_proposals"]
                    assert manager.get_project(project["id"])["status"] == "active"
                    db.update_schedule(schedule["id"], next_run_at=0)
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        if manager.get_project(project["id"])["status"] == "done":
                            break
                        time.sleep(0.1)
                    assert manager.get_project(project["id"])["status"] == "done"
                    print(
                        "The authorized tick accepted Refresh's Project completion proposal."
                    )
                    print("Intake authorization was revoked; no model call was made.")
                else:
                    print(
                        "Duplicate start returned the first run; no model call was made"
                    )
        finally:
            if db is not queue_db:
                db.close()
            with queue_db.db_engine.begin() as connection:
                connection.execute(
                    text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                )
            queue_db.close()
