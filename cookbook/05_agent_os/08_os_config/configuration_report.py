"""
Configuration Report - read how an AgentOS is set up

`GET /config` tells a settings page how the AgentOS is set up without probing routes:

- `authorization`: how requests are authenticated and authorized.
  Every caller sees `enabled`, `mode` and `user_isolation`.
  An administrator also sees `managed_roles`, `default_role`, `roles_from_token`,
  `token_scopes_trusted` and `audience_verified`.
- One top-level block per optional feature, each saying whether it is on:
  `scheduler`, `mcp`, `manager`, `media_storage`, `telemetry`, and `enabled` on
  `traces`, `filesystem` and `knowledge`. `company` is null when off, `interfaces`
  is empty and `queue.durable` is false.
  Only an administrator sees `user_directory`, `audit` and `public`.

These blocks report what the running AgentOS does, not the arguments it was given,
and none holds a key, an audience or a role's scopes.

This file builds an AgentOS with managed roles, a user directory and audit, then
reads `/config` as an administrator and as a regular member and prints both.

Run it:
    pip install "agno[os]"
    python configuration_report.py
(no OpenAI key needed - the agent is listed, never run)
"""

import json
import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization
from agno.os.authz import UserDirectory

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT secret (use an environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "configuration-report-os"

os.makedirs("tmp", exist_ok=True)
db = SqliteDb(db_file="tmp/configuration_report.db")

# Managed roles with both audit trails on. The audience check is on, so the report
# shows audience_verified: true.
authz = Authorization(
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    verify_audience=True,
    audience=OS_ID,
    audit=True,
)
authz.define_role("admin", ["agent_os:admin"])
authz.define_role("member", ["config:read", "agents:*:read"], default=True)
authz.seed(admin="alice")
authz.assign("bob", "member")

support_agent = Agent(
    id="support-agent",
    name="Support Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
)

agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS that reports its own configuration",
    agents=[support_agent],
    db=db,
    authorization=authz,
    user_directory=UserDirectory(auto_provision=True),
)

app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging

    from fastapi.testclient import TestClient

    logging.disable(logging.CRITICAL)  # quiet framework logs for a clean transcript
    client = TestClient(app)

    def auth(sub: str) -> dict:
        token = jwt.encode(
            {"sub": sub, "aud": OS_ID, "exp": datetime.now(UTC) + timedelta(hours=1)},
            JWT_SECRET,
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    def report(sub: str) -> dict:
        response = client.get("/config", headers=auth(sub))
        response.raise_for_status()
        body = response.json()
        keys = (
            "authorization",
            "user_directory",
            "audit",
            "public",
            "scheduler",
            "mcp",
            "manager",
        )
        keys += ("media_storage", "telemetry")
        report = {key: body[key] for key in keys if key in body}
        report["traces"] = {"enabled": body["traces"]["enabled"]}
        report["queue"] = body["queue"]
        return report

    print("\nalice (admin) sees the full report:")
    print(json.dumps(report("alice"), indent=2))

    print("\nbob (member) sees the mode and the feature blocks, not the admin detail:")
    print(json.dumps(report("bob"), indent=2))

    # The audit flags describe the routes that serve the trails.
    changes = client.get("/authz/audit", headers=auth("alice"))
    print(f"\nGET /authz/audit as alice -> {changes.status_code}")
