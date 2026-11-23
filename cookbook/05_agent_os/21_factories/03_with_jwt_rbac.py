"""
Grant Factory Tools from Trusted JWT Claims
===========================================

Use verified JWT claims to choose an Agent's tools per request, keep client
input out of authorization decisions, and map FactoryPermissionError to 403.

Prerequisites: none beyond OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/21_factories/03_with_jwt_rbac.py
Try: In another terminal, rerun this file with --demo
"""

import os
import sys
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from agno.agent import Agent, AgentFactory
from agno.db.sqlite import SqliteDb
from agno.factory import (
    FactoryPermissionError,
    RequestContext,
    TrustedContext,
)
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware

# ---------------------------------------------------------------------------
# Create Trusted RBAC Inputs and Tools
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
JWT_SECRET = "factory-jwt-demo-secret-with-at-least-32-bytes"

db = SqliteDb(id="jwt-rbac-factory-db", db_file="tmp/21_factories_jwt_rbac.db")


def list_documents() -> str:
    """List documents visible in the workspace."""
    return "Documents: architecture.md, roadmap.md"


def invite_member(email: str) -> str:
    """Invite a member to the workspace."""
    return f"Invited {email}"


def build_workspace_agent(ctx: RequestContext) -> Agent:
    """Grant tools from verified claims, never from factory_input."""
    role = ctx.trusted.claims.get("role")
    if role not in {"viewer", "admin"}:
        raise FactoryPermissionError("role must be viewer or admin")

    tools = [list_documents]
    if role == "admin":
        tools.append(invite_member)

    scopes = ", ".join(sorted(ctx.trusted.scopes)) or "none"
    return Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        tools=tools,
        instructions=(
            f"The verified caller role is {role}; trusted scopes are {scopes}. "
            "Use only the tools granted to this request and report their result."
        ),
    )


workspace_factory = AgentFactory(
    id="workspace-assistant",
    name="JWT Workspace Assistant",
    description="Grants tools from verified JWT role claims.",
    db=db,
    factory=build_workspace_agent,
)

agent_os = AgentOS(
    id="jwt-rbac-factory-os",
    description="AgentOS passing trusted JWT claims into a factory.",
    agents=[workspace_factory],
)
app = agent_os.get_app()
app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    validate=True,
    authorization=False,
)


def make_token(role: str, scopes: list[str]) -> str:
    """Create a short-lived, locally signed demonstration token."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": f"{role}-user",
            "role": role,
            "scopes": scopes,
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def resolved_tool_names(role: str) -> set[str]:
    """Inspect the real product of factory resolution for one trusted role."""
    agent = workspace_factory.resolve(
        RequestContext(
            user_id=f"{role}-user",
            trusted=TrustedContext(
                claims={"role": role},
                scopes=frozenset({"workspace:read"}),
            ),
        ),
        expected_type=Agent,
    )
    return {
        getattr(candidate, "name", getattr(candidate, "__name__", ""))
        for candidate in agent.tools or []
    }


def run_demo() -> None:
    """Verify role grants, live runs, trusted scopes, and the 403 path."""
    viewer_tools = resolved_tool_names("viewer")
    admin_tools = resolved_tool_names("admin")
    if viewer_tools != {"list_documents"}:
        raise RuntimeError(f"Viewer received the wrong tools: {viewer_tools}")
    if admin_tools != {"list_documents", "invite_member"}:
        raise RuntimeError(f"Admin received the wrong tools: {admin_tools}")

    viewer_token = make_token("viewer", ["workspace:read"])
    admin_token = make_token("admin", ["workspace:read", "workspace:write"])
    guest_token = make_token("guest", ["workspace:read"])

    with httpx.Client(base_url=BASE_URL, timeout=90.0) as client:
        viewer_response = client.post(
            f"/agents/{workspace_factory.id}/runs",
            data={
                "message": "List the workspace documents.",
                "stream": "false",
            },
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        viewer_response.raise_for_status()
        viewer_run = viewer_response.json()

        admin_response = client.post(
            f"/agents/{workspace_factory.id}/runs",
            data={
                "message": "Invite dev@example.com to the workspace.",
                "stream": "false",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        admin_response.raise_for_status()
        admin_run = admin_response.json()

        denied_response = client.post(
            f"/agents/{workspace_factory.id}/runs",
            data={
                "message": "This request must not reach a model.",
                "stream": "false",
            },
            headers={"Authorization": f"Bearer {guest_token}"},
        )
        if denied_response.status_code != 403:
            raise RuntimeError(
                f"FactoryPermissionError returned {denied_response.status_code}"
            )

    if viewer_run["status"] != "COMPLETED" or admin_run["status"] != "COMPLETED":
        raise RuntimeError("A permitted JWT factory run did not complete")

    print(f"Viewer tools: {sorted(viewer_tools)}")
    print(f"Admin tools: {sorted(admin_tools)}")
    print(f"Viewer run: {viewer_run['run_id']} -> {viewer_run['status']}")
    print(f"Admin run: {admin_run['run_id']} -> {admin_run['status']}")
    print(f"Unsupported role: {denied_response.status_code}")


# ---------------------------------------------------------------------------
# Run Factory AgentOS or Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        agent_os.serve(app=app)
