"""
Service accounts for machine-to-machine authentication
======================================================

Mint an opaque agno_pat_ token, use its current default scopes, and revoke it.
Only the token hash is stored; the plaintext appears once in the create
response. The local smoke proves mint, scoped access, and immediate rejection
after revocation on the same worker.

Prerequisites: none
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/service_accounts.py
Try: inspect the printed automated lifecycle summary, then browse /docs
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.service_accounts import DEFAULT_SERVICE_ACCOUNT_SCOPES
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create AgentOS with JWT operators and service accounts
# ---------------------------------------------------------------------------

OS_ID = "service-account-security-demo"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY", "development-secret-at-least-256-bits-long"
)

db = SqliteDb(db_file="tmp/security_service_accounts.db")
assistant_agent = Agent(
    id="assistant-agent",
    name="Assistant Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)
agent_os = AgentOS(
    id=OS_ID,
    agents=[assistant_agent],
    db=db,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
    ),
)
app = agent_os.get_app()


def make_admin_token() -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "security-operator",
            "aud": OS_ID,
            "scopes": ["agent_os:admin"],
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def run_smoke() -> dict[str, object]:
    account_name = f"cookbook-{uuid4().hex[:10]}"
    admin_token = make_admin_token()

    with TestClient(app) as client:
        created = client.post(
            "/service-accounts",
            json={"name": account_name},
            headers=_auth(admin_token),
        )
        assert created.status_code == 201, created.text
        created_body = created.json()
        service_token = created_body["token"]
        account_id = created_body["id"]

        observed_scopes = [item["raw"] for item in created_body["scopes"]]
        listed = client.get("/service-accounts", headers=_auth(admin_token))
        listed_ids = [item["id"] for item in listed.json()["data"]]
        config_status = client.get("/config", headers=_auth(service_token)).status_code
        management_status = client.get(
            "/service-accounts", headers=_auth(service_token)
        ).status_code
        revoke_status = client.delete(
            f"/service-accounts/{account_id}",
            headers=_auth(admin_token),
        ).status_code
        revoked_status = client.get("/config", headers=_auth(service_token)).status_code

    assert service_token.startswith("agno_pat_")
    assert observed_scopes == DEFAULT_SERVICE_ACCOUNT_SCOPES
    assert listed.status_code == 200
    assert account_id in listed_ids
    assert config_status == 200
    assert management_status == 403
    assert revoke_status == 204
    assert revoked_status == 401
    return {
        "principal": created_body["principal"],
        "scopes": observed_scopes,
        "listed": account_id in listed_ids,
        "config_status": config_status,
        "management_status": management_status,
        "revoke_status": revoke_status,
        "revoked_status": revoked_status,
    }


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    service_account_result = run_smoke()
    print("Service-account lifecycle smoke passed:")
    print(service_account_result)
    print(
        "\nDefault scopes: agents:run, teams:run, workflows:run, "
        "sessions:read, config:read."
    )
    print(
        "Successful verification is cached for 30 seconds by default; "
        "same-worker revocation evicts the cache immediately."
    )
    agent_os.serve(app=app, port=7777)
