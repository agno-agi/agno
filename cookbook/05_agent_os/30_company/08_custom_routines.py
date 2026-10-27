"""Create a template-free Routine and save an agent-discovered website Source.

Run: .venv/bin/python cookbook/05_agent_os/30_company/08_custom_routines.py
The example makes no model calls, website requests, or outbound deliveries.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from agno.agent import Agent
from agno.company import Product, Routine
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.run.base import RunContext
from agno.tools.company import CompanyTools
from fastapi.testclient import TestClient

if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=str(Path(directory) / "company.db"))
        tools = CompanyTools(db)
        researcher = Agent(id="researcher", tools=[tools], db=db, telemetry=False)
        product = Product(
            id="research",
            name="Research",
            routines=[
                Routine(
                    name="watch",
                    executor_type="agent",
                    executor_id="researcher",
                    instructions="Find relevant release pages. Save useful website Sources. Read selected pages and "
                    "propose evidence-backed Tasks only for actionable changes. A quiet check needs no Task.",
                )
            ],
        )
        agent_os = AgentOS(
            db=db,
            agents=[researcher],
            company=CompanyConfig(products=[product]),
            telemetry=False,
        )
        with TestClient(agent_os.get_app()) as client:
            routine = client.get("/company/routines").json()["data"][0]
            assert routine["payload"]["metadata"]["template"] is None
            path = "/company/routines/" + routine["id"]
            assert client.get(path).json() == routine
            assert routine["schedule_type"] == "on_demand"
            assert routine["enabled"] and routine["next_run_at"] is None
            assert routine["last_run"] is None
            # An on-demand Routine has no schedule to pause, and it is already enabled.
            assert client.post(path + "/pause").status_code == 409
            assert client.post(path + "/resume").status_code == 409
            scheduled = client.patch(path, json={"cron_expr": "0 9 * * *"}).json()
            assert (
                scheduled["schedule_type"] == "scheduled" and scheduled["next_run_at"]
            )
            manual = client.patch(path, json={"cron_expr": None}).json()
            assert (
                manual["schedule_type"] == "on_demand" and manual["next_run_at"] is None
            )
            assert client.get("/company/sources").json()["data"] == []
            # The runtime injects these identities during a real agent run.
            context = RunContext(
                run_id="example-discovery", session_id="example-session"
            )
            arguments = dict(
                product_id="research",
                reference="https://docs.agno.com/",
                _agno_agent=researcher,
                _agno_run_context=context,
            )
            source = json.loads(tools.add_product_source(**arguments))
            assert (
                json.loads(tools.add_product_source(**arguments))["id"] == source["id"]
            )
            assert source["config"]["metadata"]["agent_id"] == "researcher"
            print("Created a custom Routine without a template or initial Sources.")
            print("Repeated website discovery reused one attributed Source.")
            assert client.delete("/company/sources/" + source["id"]).status_code == 204
            assert client.get("/company/sources").json()["data"] == []
            print("The human archived the discovered Source.")
        db.close()
