"""Do Company work through Super Agent and exercise its Company tools without a model call.

With CompanyConfig set, Super Agent holds the Company tools itself: company details,
Products, Projects, Tasks, Sources, playbook, Routines and decisions. A Routine with no
executor runs on Mini Agent, a restricted agent that can only propose work.

Prerequisites: Install agno, sqlalchemy, openai, fastapi and httpx.
Run: .venv/bin/python cookbook/05_agent_os/30_company/05_super_agent_company.py
Try: With provider credentials, call agent_os.manager.print_response(...).
"""

import json
from tempfile import TemporaryDirectory

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.run import RunContext
from agno.tools.company import CompanyTools
from fastapi.testclient import TestClient

if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=directory + "/company.db")
        model = OpenAIResponses(id="gpt-5.6-luna")
        agent_os = AgentOS(
            db=db,
            manager=OSManager(model=model, access_docs=False),
            company=CompanyConfig(model=model),
            user_isolation=True,
            telemetry=False,
        )
        super_agent = agent_os.manager
        assert super_agent is not None
        tools = next(t for t in super_agent.tools if isinstance(t, CompanyTools))
        # Super Agent does not hold the Routine-only maintenance and summary tools.
        assert "update_company_details" in tools.functions
        assert "create_product_routine" in tools.functions
        assert "refresh_company_product" not in tools.functions
        assert "summarize_company_product" not in tools.functions
        assert not any(
            "transition" in name or "schedule" in name for name in tools.functions
        )

        # Company details are initialized when the app starts.
        with TestClient(agent_os.get_app()) as client:
            # Trusted application code supplies context. HTTP and MCP inject their
            # authenticated caller automatically; identity is never a model argument.
            context = RunContext(run_id="demo", session_id="planning", user_id="alice")
            # Chat step: "Our company is Acme. We build documentation tools."
            tools.update_company_details(
                name="Acme",
                description="We build documentation tools.",
                _agno_run_context=context,
            )
            # Chat step: "Set up a Product for our docs site with an intake Routine."
            # These are the tool calls Super Agent makes, without a paid model call.
            product = json.loads(
                tools.create_company_product(
                    name="Documentation",
                    purpose="Help people build reliable agents",
                    sources=[{"type": "website", "reference": "https://docs.agno.com"}],
                    routines=[
                        # No executor is named, so the Routine runs on Mini Agent.
                        {"name": "intake", "template": "intake"}
                    ],
                    _agno_team=super_agent,
                    _agno_run_context=context,
                )
            )
            project = json.loads(
                tools.propose_company_project(
                    product["id"], "Release", _agno_run_context=context
                )
            )
            proposal = json.loads(
                tools.propose_company_task(
                    product["id"],
                    "Draft release notes",
                    brief="Summarize reviewed changes",
                    project_id=project["id"],
                    _agno_run_context=context,
                )
            )
            assert proposal["status"] == "backlog" and proposal["user_id"] == "alice"
            tools.update_product_status(
                product["id"],
                "# Status\n\nRelease notes proposed.\n",
                1,
                _agno_run_context=context,
            )
            tools.log_company_decision(
                "Review release notes before publishing",
                reasoning="Human approval required",
                _agno_run_context=context,
            )

            assert client.get("/company/details").json()["name"] == "Acme"
            assert len(client.get("/company/sources").json()["data"]) == 1
            routine = client.get("/company/routines").json()["data"][0]
            assert routine["target_type"] == "agent"
            assert routine["target_id"] == "miniagent"
            # Mini Agent runs unattended work: it is not listed and has no chat card.
            listed = [agent["id"] for agent in client.get("/agents").json()]
            assert "miniagent" not in listed
            team = client.get("/teams/superagent").json()
            assert [m["id"] for m in team["members"]] == ["platform-builder"]
        schedule = db.get_schedule(routine["id"])
        assert schedule["endpoint"] == "/agents/miniagent/runs"
        db.close()
        print("Super Agent saved company details, a Product, a Routine and a proposal")
        print("No model call was made")
