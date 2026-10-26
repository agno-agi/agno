"""Inspect verified tenant identity without model calls or external services.

Run: PYTHONPATH=libs/agno .venv/bin/python cookbook/05_agent_os/26_authorization/16_verified_tenant_identity.py

This establishes identity only. It does not isolate sessions, databases, skills,
MCP connections or other resources. Applications must authorize resource access.
"""

from datetime import datetime, timedelta, timezone

import jwt
from agno.agent import Agent
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.os.utils import build_request_context
from fastapi import Request
from fastapi.testclient import TestClient

# Local demonstration key only. Production deployments use their IdP's verification keys.
DEMO_SECRET = "local-tenant-identity-demo-key-do-not-deploy"

agent_os = AgentOS(
    telemetry=False,
    agents=[Agent(id="identity-demo")],
    authorization=Authorization(
        verification_keys=[DEMO_SECRET],
        algorithm="HS256",
        tenant_claim="org_id",
    ),
)
app = agent_os.get_app()


@app.post("/identity")
async def identity(request: Request):
    ctx = build_request_context(request)
    return {"user_id": request.state.user_id, "tenant_id": ctx.tenant_id}


if __name__ == "__main__":
    with TestClient(app) as client:
        for tenant in ("acme", "globex"):
            token = jwt.encode(
                {
                    "sub": "same-user",
                    "org_id": tenant,
                    "scopes": ["agent_os:admin"],
                    "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                },
                DEMO_SECRET,
                algorithm="HS256",
            )
            response = client.post(
                "/identity?tenant_id=forged",
                headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": "forged"},
                json={"tenant_id": "forged"},
            )
            response.raise_for_status()
            assert response.json() == {"user_id": "same-user", "tenant_id": tenant}
            print(response.json())
    print(
        "Verified tenant identity is preserved, including for admins. Resource isolation is separate."
    )
