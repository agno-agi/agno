"""Configure Company Manager and exercise its bounded tools without a model call.

Prerequisites: Install agno, sqlalchemy, openai, fastapi, httpx and fastmcp.
Run: .venv/bin/python cookbook/05_agent_os/30_company/05_company_manager.py
Try: With provider credentials, call agent_os.company_manager.print_response(...).
     Add manager=OSManager() to compose Company Manager as an OS Manager member.
"""

import json
from tempfile import TemporaryDirectory

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, MCPConfig
from agno.registry import Registry
from agno.run import RunContext
from agno.tools.company import CompanyTools
from fastapi.testclient import TestClient

if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=directory + "/company.db")
        tools = CompanyTools(db, user_isolation=True)
        model = OpenAIResponses(id="gpt-5.6-luna")
        agent_os = AgentOS(
            db=db,
            registry=Registry(
                models=[model],
                agents=[Agent(id="intake-reader", model=model, tools=[tools])],
            ),
            company=CompanyConfig(),
            user_isolation=True,
            mcp=MCPConfig(tools=[tools]),
            telemetry=False,
        )
        # Trusted application code supplies context. HTTP and MCP inject their
        # authenticated caller automatically; identity is never a model argument.
        context = RunContext(run_id="demo", session_id="planning", user_id="alice")
        # Chat step: "Set up a Product for our docs site with an intake Routine."
        # Exercise the same tool call Company Manager makes, without a paid model call.
        product = json.loads(
            tools.create_company_product(
                name="Documentation",
                purpose="Help people build reliable agents",
                sources=[{"type": "website", "reference": "https://docs.agno.com"}],
                routines=[
                    {
                        "name": "intake",
                        "template": "intake",
                        "executor_type": "agent",
                        "executor_id": "intake-reader",
                    }
                ],
                _agno_agent=agent_os.company_manager,
                _agno_run_context=context,
            )
        )
        assert (
            json.loads(tools.list_company_products(_agno_run_context=context))["data"][
                0
            ]["id"]
            == product["id"]
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
        with TestClient(agent_os.get_app()) as client:
            response = client.get("/agents/company-manager-internal")
            assert response.status_code == 200
            assert len(client.get("/company/sources").json()["data"]) == 1
            assert len(client.get("/company/routines").json()["data"]) == 1
        assert agent_os.company_manager is not None
        assert agent_os.company_manager not in agent_os.registry.agents
        assert not any(
            "transition" in name or "schedule" in name for name in tools.functions
        )
        db.close()
        print("Company Manager configured; Backlog proposal, status and decision saved")
        print("No model call was made")
