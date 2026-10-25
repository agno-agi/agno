"""Declare a Product heartbeat and deduplicate source Intake without a model call.

Prerequisites: Install agno, sqlalchemy, fastapi, httpx, croniter and pytz.
Run: .venv/bin/python cookbook/05_agent_os/30_company/07_heartbeat.py
Try: Edit release.md between scans; the same issue still has one Backlog Task.
     Change metadata.archive_window_days to control retention of terminal work.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from time import time

from agno.agent import Agent
from agno.company import CompanyManager, Product, Routine, Source
from agno.company.routines import load_routine_skills
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.tools.company import CompanyTools
from fastapi.testclient import TestClient

if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        release = Path(directory) / "release.md"
        release.write_text("# Release\nDocument the new API.\n")
        db = SqliteDb(db_file=str(Path(directory) / "company.db"))
        reader = Agent(
            id="source-reader",
            db=db,
            tools=[CompanyTools(db)],
            skills=load_routine_skills(),
            telemetry=False,
        )
        product = Product(
            name="Documentation",
            purpose="Keep docs current with released SDK behavior",
            sources=[Source(type="markdown", reference=str(release))],
            routines=[
                Routine(
                    name="intake",
                    template="intake",
                    executor_type="agent",
                    executor_id=reader.id,
                    cron_expr="0 9 * * 1-5",
                )
            ],
        )
        agent_os = AgentOS(
            db=db,
            agents=[reader],
            company=CompanyConfig(products=[product]),
            telemetry=False,
        )
        with TestClient(agent_os.get_app()) as client:
            records = client.get("/company/products").json()["data"]
            product_id = records[0]["id"]
            source = client.get(
                "/company/sources", params={"product_id": product_id}
            ).json()["data"][0]
            manager = CompanyManager(db)
            # Offline stand-in for the reader's decision after inspecting the Source.
            index = manager.browse_source(source["id"], "first-scan")
            selected_path = index["data"][0]["path"]
            evidence = [
                manager.browse_source(source["id"], "first-scan", path=selected_path)
            ]
            proposal = dict(
                title="Document the new API",
                brief="Explain the released API with an example.",
                proposal_key="new-api-docs",
                evidence_links=[evidence[0]["link"]],
                evidence_hashes={evidence[0]["link"]: evidence[0]["content_hash"]},
            )
            project = manager.create_project(
                product_id=product_id, name="Review the release"
            )
            first = manager.intake(
                source_id=source["id"],
                run_id="first-scan",
                proposal=proposal,
                project_id=project["id"],
            )
            release.write_text("# Release\nDocument the new API and its options.\n")
            evidence = [
                manager.browse_source(source["id"], "repeat-scan", path=selected_path)
            ]
            proposal["evidence_hashes"] = {
                item["link"]: item["content_hash"] for item in evidence
            }
            again = manager.intake(
                source_id=source["id"],
                run_id="repeat-scan",
                proposal=proposal,
                project_id=project["id"],
            )
            assert first["id"] == again["id"]
            assert first["status"] == "backlog"
            manager.transition_project(
                project_id=project["id"], target="active", reason="Human accepted scope"
            )
            manager.transition_task(
                task_id=first["id"],
                target="cancelled",
                reason="Replaced by the release guide",
            )
            refresh = manager.refresh(product_id)
            assert refresh["completion_proposals"][0]["project_id"] == project["id"]
            assert manager.get_project(project["id"])["status"] == "active"
            manager.transition_project(
                project_id=project["id"],
                target="done",
                reason="Human reviewed all terminal Tasks",
            )
            # Seed an old terminal record to exercise the time window without waiting.
            db.create_task(
                dict(
                    id="old-terminal",
                    product_id=product_id,
                    project_id=project["id"],
                    title="Old completed work",
                    status="done",
                    created_at=int(time()) - 15 * 86400,
                    transitions=[],
                )
            )
            assert "old-terminal" in manager.refresh(product_id)["archived_tasks"]
            assert manager.get_task("old-terminal") is None
            assert manager.restore_task("old-terminal")["status"] == "done"
            routine = client.get("/company/routines").json()["data"][0]
            assert routine["managed_by"] == "company"
            assert routine["payload"]["metadata"]["auto_accept"] is False
            assert routine["id"] in records[0]["metadata"]["routine_ids"]
            client.post(
                "/company/routines/" + routine["id"] + "/pause"
            ).raise_for_status()
            print(
                "Repeated evidence kept one Backlog proposal with its original run id."
            )
            print("Routine is an ordinary paused scheduler row; no model was called.")
            print(
                "Refresh proposed completion, archived old work, and retained restore support."
            )
        db.close()
