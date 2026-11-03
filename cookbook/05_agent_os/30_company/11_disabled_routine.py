"""Keep a scheduled Routine visible but inactive until a human enables it.

Run: .venv/bin/python cookbook/05_agent_os/30_company/11_disabled_routine.py
This example makes no model calls and does not start a scheduler.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from agno.agent import Agent
from agno.company import Product, Routine
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from fastapi.testclient import TestClient

if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=str(Path(directory) / "company.db"))
        reviewer = Agent(id="reviewer", db=db, telemetry=False)
        product = Product(
            id="documentation",
            name="Documentation",
            routines=[
                Routine(
                    name="daily-review",
                    executor_type="agent",
                    executor_id="reviewer",
                    instructions="Review documentation and propose useful improvements.",
                    cron_expr="0 9 * * *",
                    enabled=False,
                ),
            ],
        )
        agent_os = AgentOS(
            db=db,
            agents=[reviewer],
            company=CompanyConfig(products=[product]),
            telemetry=False,
        )
        with TestClient(agent_os.get_app()) as client:
            routine = client.get("/company/routines").json()["data"][0]
            assert routine["enabled"] is False
            path = "/company/routines/" + routine["id"]
            # The UI uses this endpoint when a human enables the Routine.
            resumed = client.post(path + "/resume")
            assert resumed.status_code == 200
            assert resumed.json()["enabled"] is True

        # Startup declarations preserve the human's choice on restart.
        with TestClient(agent_os.get_app()) as client:
            assert client.get(path).json()["enabled"] is True
        db.close()
        print(
            "The Routine started disabled, remained visible, and retained activation after restart."
        )
