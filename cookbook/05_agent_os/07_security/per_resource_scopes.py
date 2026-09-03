"""
Per-resource and wildcard scopes
================================

Grant access to one agent, team, or workflow by id, or use a wildcard scope
deliberately. The smoke shows list filtering across all three resource families
without invoking a model.

Prerequisites: none for the smoke; OPENAI_API_KEY for live agent/team runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/per_resource_scopes.py
Try: compare the printed specific-resource and wildcard tokens
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.team import Team
from agno.workflow import Workflow
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create resources and scoped AgentOS
# ---------------------------------------------------------------------------

OS_ID = "resource-scope-demo"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY", "development-secret-at-least-256-bits-long"
)

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.5"),
)
private_agent = Agent(
    id="private-agent",
    name="Private Agent",
    model=OpenAIResponses(id="gpt-5.5"),
)
research_team = Team(
    id="research-team",
    name="Research Team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[research_agent],
)


def review_step(session_state: dict | None = None) -> str:
    """A local workflow step used only to register a workflow resource."""
    state = session_state or {}
    return str(state.get("document", "No document supplied"))


review_workflow = Workflow(
    id="review-workflow",
    name="Review Workflow",
    steps=review_step,
)

agent_os = AgentOS(
    id=OS_ID,
    agents=[research_agent, private_agent],
    teams=[research_team],
    workflows=[review_workflow],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
    ),
)
app = agent_os.get_app()


def make_token(subject: str, scopes: list[str]) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "aud": OS_ID,
            "scopes": scopes,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def run_smoke() -> tuple[
    dict[str, dict[str, list[str]]],
    str,
    str,
]:
    specific_token = make_token(
        "specific-user",
        [
            "agents:research-agent:read",
            "agents:research-agent:run",
            "teams:research-team:read",
            "teams:research-team:run",
            "workflows:review-workflow:read",
            "workflows:review-workflow:run",
        ],
    )
    wildcard_token = make_token(
        "wildcard-user",
        [
            "agents:*:read",
            "agents:*:run",
            "teams:*:read",
            "teams:*:run",
            "workflows:*:read",
            "workflows:*:run",
        ],
    )

    with TestClient(app) as client:
        specific_headers = {"Authorization": f"Bearer {specific_token}"}
        wildcard_headers = {"Authorization": f"Bearer {wildcard_token}"}
        specific_resources = {
            "agents": sorted(
                item["id"]
                for item in client.get("/agents", headers=specific_headers).json()
            ),
            "teams": sorted(
                item["id"]
                for item in client.get("/teams", headers=specific_headers).json()
            ),
            "workflows": sorted(
                item["id"]
                for item in client.get("/workflows", headers=specific_headers).json()
            ),
        }
        wildcard_resources = {
            "agents": sorted(
                item["id"]
                for item in client.get("/agents", headers=wildcard_headers).json()
            ),
            "teams": sorted(
                item["id"]
                for item in client.get("/teams", headers=wildcard_headers).json()
            ),
            "workflows": sorted(
                item["id"]
                for item in client.get("/workflows", headers=wildcard_headers).json()
            ),
        }

    assert specific_resources == {
        "agents": ["research-agent"],
        "teams": ["research-team"],
        "workflows": ["review-workflow"],
    }, specific_resources
    assert wildcard_resources == {
        "agents": ["private-agent", "research-agent"],
        "teams": ["research-team"],
        "workflows": ["review-workflow"],
    }, wildcard_resources
    return (
        {
            "specific": specific_resources,
            "wildcard": wildcard_resources,
        },
        specific_token,
        wildcard_token,
    )


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    visible_resources, specific_token, wildcard_token = run_smoke()
    print("Resources visible by scope:")
    print(visible_resources)
    print("\nSpecific-resource token:")
    print(specific_token)
    print("\nWildcard token:")
    print(wildcard_token)
    agent_os.serve(app=app, port=7777)
