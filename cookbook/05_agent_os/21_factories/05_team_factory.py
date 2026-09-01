"""
Build a Team per Request
========================

Register a TeamFactory that creates a fresh two-role support Team with
tenant-specific instructions for every Team run.

Prerequisites: none beyond OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/21_factories/05_team_factory.py
Try: In another terminal, rerun this file with --demo
"""

import os
import sys

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team, TeamFactory

# ---------------------------------------------------------------------------
# Create a Per-Request Team Factory
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
db = SqliteDb(id="team-factory-db", db_file="tmp/21_factories_team.db")


def build_support_team(ctx: RequestContext) -> Team:
    """Build a tenant-aware billing and technical support Team."""
    tenant = ctx.user_id or "anonymous"
    billing = Agent(
        id="billing-specialist",
        name="Billing Specialist",
        role="Resolve billing questions.",
        model=OpenAIResponses(id="gpt-5.5"),
        instructions=f"Handle billing questions for tenant {tenant}.",
    )
    technical = Agent(
        id="technical-specialist",
        name="Technical Specialist",
        role="Resolve technical questions.",
        model=OpenAIResponses(id="gpt-5.5"),
        instructions=f"Handle technical questions for tenant {tenant}.",
    )
    return Team(
        id="product-team-id-is-overridden",
        name="Tenant Support Team",
        model=OpenAIResponses(id="gpt-5.5"),
        members=[billing, technical],
        instructions=[
            f"Coordinate support for tenant {tenant}.",
            "Delegate billing and technical work to the matching specialist.",
            "Return a concise combined answer that names the tenant.",
        ],
    )


support_factory = TeamFactory(
    id="tenant-support-team",
    name="Tenant Support Team Factory",
    description="Builds a fresh billing and technical Team per request.",
    db=db,
    factory=build_support_team,
)

agent_os = AgentOS(
    id="team-factory-os",
    description="AgentOS resolving a TeamFactory per request.",
    teams=[support_factory],
)
app = agent_os.get_app()


def verify_team_resolution() -> None:
    """Inspect identity, persistence, event storage, and Team membership."""
    team = support_factory.resolve(
        RequestContext(user_id="acme"),
        expected_type=Team,
    )
    if team.id != support_factory.id or team.db is not db:
        raise RuntimeError("TeamFactory did not enforce identity and database")
    if team.store_events is not True or len(team.members) != 2:
        raise RuntimeError("Resolved Team lost event storage or its members")


def run_demo() -> None:
    """Discover and run the live Team factory."""
    verify_team_resolution()
    with httpx.Client(base_url=BASE_URL, timeout=180.0) as client:
        health = client.get("/health")
        health.raise_for_status()

        teams_response = client.get("/teams")
        teams_response.raise_for_status()
        factory = next(
            team for team in teams_response.json() if team["id"] == support_factory.id
        )
        if factory["is_factory"] is not True:
            raise RuntimeError("Team discovery did not mark the factory")

        run_response = client.post(
            f"/teams/{support_factory.id}/runs",
            data={
                "message": (
                    "For tenant acme, explain how to diagnose a duplicate "
                    "invoice caused by a retry."
                ),
                "user_id": "acme",
                "stream": "false",
            },
        )
        run_response.raise_for_status()
        run = run_response.json()
        if run["status"] != "COMPLETED" or "acme" not in run["content"].lower():
            raise RuntimeError("The live Team factory run lost its tenant context")

    print(f"Health: {health.json()['status']}")
    print(f"Factory: {factory['id']} (is_factory={factory['is_factory']})")
    print("Resolved Team: 2 members, inherited DB, stored events")
    print(f"Run: {run['run_id']} -> {run['status']}")
    print(f"Response: {run['content']}")


# ---------------------------------------------------------------------------
# Run Factory AgentOS or Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        agent_os.serve(app=app)
