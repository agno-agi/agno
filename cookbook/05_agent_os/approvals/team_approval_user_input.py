"""
Team Approval with User Input (AgentOS)
========================================

Approval + user input HITL on a team: member agent has @approval + @tool(requires_user_input=True).
Run with: python libs/agno/agno/test.py
"""

import os
from typing import Optional

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team.team import Team
from agno.tools import tool

DB_FILE = "tmp/team_approvals_test.db"


@approval(type="required")
@tool(requires_user_input=True, user_input_fields=["service", "environment", "version"])
def collect_deployment_specs(
    service: Optional[str] = None,
    environment: Optional[str] = None,
    version: Optional[str] = None,
) -> str:
    """Collect deployment specifications from the user.

    Args:
        service (str): Name of the service to deploy.
        environment (str): Target environment (staging, production).
        version (str): Version to deploy.
    """
    return f"Deployment specs collected: service={service}, environment={environment}, version={version}"


@approval(type="required")
@tool(requires_confirmation=True)
def approve_deployment(service: str, environment: str, version: str) -> str:
    """Approve and execute a deployment.

    Args:
        service (str): Name of the service.
        environment (str): Target environment.
        version (str): Version to deploy.
    """
    return f"Deployment approved: {service} v{version} to {environment}"


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file=DB_FILE, session_table="team_sessions", approvals_table="approvals")

spec_collector = Agent(
    name="Deployment Spec Collector",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[collect_deployment_specs],
    instructions=["Call collect_deployment_specs immediately when asked about deployments."],
)

deploy_team = Team(
    id="deploy-approval-team",
    name="Deployment Approval Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[spec_collector],
    tools=[approve_deployment],
    instructions=[
        "Delegate to the Deployment Spec Collector to gather deployment details.",
        "Once specs are collected, call approve_deployment with those specs.",
    ],
    db=db,
)

agent_os = AgentOS(
    description="Team approval example: member collects specs (user input) + team approves (confirmation)",
    teams=[deploy_team],
    db=db,
)
app = agent_os.get_app()

if __name__ == "__main__":
    # Clean up from previous runs
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    os.makedirs("tmp", exist_ok=True)

    agent_os.serve(app="team_approval_user_input:app", port=7777, reload=True)
