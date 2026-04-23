"""JWT-Driven Factory -- RBAC tool grants from trusted claims.

Demonstrates the trust split: authorization decisions (which tools to grant)
come from `ctx.trusted.claims` (set by verified JWT middleware), while
non-privileged customization comes from `ctx.input` (untrusted client input).

This is the most realistic multi-tenant pattern. The factory uses the JWT role
to decide tool access, and the client can customize the theme but not escalate
their privileges.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/factories/agent/03_jwt_role_factory.py

Test:
    # Generate test tokens (printed at startup) and use them:

    # As viewer (read-only tools)
    curl -X POST http://localhost:7777/agents/workspace-agent/runs \
        -H "Authorization: Bearer <VIEWER_TOKEN>" \
        -F 'message=List the workspace documents' \
        -F 'factory_input={"theme": "dark"}' \
        -F 'stream=false'

    # As admin (full tool access)
    curl -X POST http://localhost:7777/agents/workspace-agent/runs \
        -H "Authorization: Bearer <ADMIN_TOKEN>" \
        -F 'message=Add member jane@acme.com as editor' \
        -F 'factory_input={"theme": "light"}' \
        -F 'stream=false'
"""

from datetime import UTC, datetime, timedelta
from typing import Literal, Optional

import jwt as pyjwt
from agno.agent import Agent, AgentFactory
from agno.db.postgres import PostgresDb
from agno.factory import FactoryPermissionError, RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JWT_SECRET = "a-string-secret-at-least-256-bits-long"

db = PostgresDb(
    id="factory-jwt-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)


# ---------------------------------------------------------------------------
# Simulated tools (replace with real implementations)
# ---------------------------------------------------------------------------


def read_docs() -> str:
    """Read workspace documents."""
    return "Document list: [design-spec.md, roadmap.md, api-docs.md]"


def write_docs(title: str, content: str) -> str:
    """Create or update a workspace document."""
    return f"Document '{title}' saved."


def manage_members(action: str, email: str) -> str:
    """Add or remove workspace members."""
    return f"Member {email} {action}d."


# ---------------------------------------------------------------------------
# Input schema (untrusted -- cosmetic only)
# ---------------------------------------------------------------------------


class WorkspaceInput(BaseModel):
    theme: Literal["light", "dark"] = "light"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_workspace_agent(ctx: RequestContext) -> Agent:
    """Build an agent whose tools depend on the caller's JWT role."""
    # Trusted: from verified JWT middleware (request.state.claims)
    claims = ctx.trusted.claims
    role = claims.get("role")
    org_id = claims.get("org_id", "unknown")

    if not role:
        raise FactoryPermissionError("JWT must contain a 'role' claim")

    # Untrusted: from client request body (factory_input)
    cfg: Optional[WorkspaceInput] = ctx.input
    theme = cfg.theme if cfg else "light"

    # Role-based tool grants
    tools = [read_docs]
    if role in ("admin", "editor"):
        tools.append(write_docs)
    if role == "admin":
        tools.append(manage_members)

    return Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        db=db,
        tools=tools,
        instructions=(
            f"You are a workspace assistant for org {org_id}.\n"
            f"The caller's role is: {role}.\n"
            f"UI theme: {theme}.\n"
            "Only use the tools available to you."
        ),
        add_datetime_to_context=True,
        markdown=True,
    )


workspace_factory = AgentFactory(
    db=db,
    id="workspace-agent",
    name="Workspace Agent",
    description="RBAC workspace agent -- tools depend on JWT role",
    factory=build_workspace_agent,
    input_schema=WorkspaceInput,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="factory-jwt-demo",
    description="Demo: JWT-driven agent factory with RBAC tool grants",
    agents=[workspace_factory],
)
app = agent_os.get_app()

# Standard JWTMiddleware -- now sets request.state.claims automatically
app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    user_id_claim="sub",
    validate=False,  # Set True in production
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    def make_token(role: str, org_id: str = "acme", user_id: str = "user_1") -> str:
        payload = {
            "sub": user_id,
            "role": role,
            "org_id": org_id,
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iat": datetime.now(UTC),
        }
        return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

    print("Test tokens (valid for 24h):")
    print()
    print(f"  VIEWER:  {make_token('viewer')}")
    print(f"  EDITOR:  {make_token('editor')}")
    print(f"  ADMIN:   {make_token('admin')}")
    print()

    agent_os.serve(app="03_jwt_role_factory:app", port=7777, reload=True)
