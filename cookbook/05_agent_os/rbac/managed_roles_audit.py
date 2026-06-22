"""
Managed Roles - the audit trail (who changed what, and every allow/deny)

New to this? Read managed_roles.py first.

Once people can change roles at runtime, you need to answer two questions later:

  1. "Who gave Bob admin, and when?"        -> the CHANGE trail
  2. "Was Alice allowed to delete that?"    -> the DECISION trail

agno keeps these as two separate, append-only tables (rows are only ever inserted,
never updated or deleted - tamper-evident, the kind of thing an auditor wants):

  - authz_audit      : one row per role/assignment change, with the actor and a
                       before/after diff.
  - authz_decisions  : one row per protected request, allow or deny, with the
                       route, the scopes required, and a NON-secret reference to
                       the token used (its `jti`, or a short hash - never the token
                       itself).

You turn it on by handing the store (and the OS) a `DbAuditSink` pointed at a DB.
That's it - every change and every decision is recorded from then on.

This file makes a few role changes and a couple of real requests, then prints both
trails. No server, no OpenAI key needed.

Run it:
    pip install "agno[roles]"
    python managed_roles_audit.py
"""

from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.authz.audit import DbAuditSink
from agno.os.authz.role_store import ManagedRoleStore
from agno.os.config import AuthorizationConfig
from fastapi.testclient import TestClient

SECRET = "managed-roles-audit-demo-secret-at-least-256-bits-long-xx"
OS_ID = "audit-demo-os"


def token(sub: str) -> dict:
    t = jwt.encode(
        {
            "sub": sub,
            "aud": OS_ID,
            "scopes": [],
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {t}"}


def main() -> None:
    # One DB for everything; the SAME sink records both trails.
    audit = DbAuditSink(db_url="sqlite:///tmp/audit_demo.db")
    store = ManagedRoleStore(db_url="sqlite:///tmp/audit_demo.db", audit=audit)

    # --- role changes (each is recorded on the change trail, with the actor) ---
    store.set_role_scopes("viewer", ["agents:*:read"], actor="alice")
    store.set_role_scopes(
        "viewer", ["agents:*:read", "agents:research-agent:run"], actor="alice"
    )  # widened
    store.assign("bob", "viewer", actor="alice")

    # --- a couple of real requests (each is recorded on the decision trail) ---
    agent = Agent(id="research-agent", name="Research Agent", db=InMemoryDb())
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=store.provider,
            audit=audit,  # <- decision audit on
        ),
    )
    client = TestClient(agent_os.get_app())
    client.get(
        "/agents/research-agent", headers=token("bob")
    )  # allowed (viewer can read)
    client.post(
        "/agents/research-agent/runs", headers=token("nobody"), data={"message": "hi"}
    )  # denied

    # --- read both trails back ---
    print("\n=== CHANGE TRAIL (authz_audit) — who changed what ===")
    for e in store.audit_log(limit=20):
        print(
            f"  {e['actor'] or 'system':>6}  {e['action']:<16} {e['target']:<10} {e.get('before')} -> {e.get('after')}"
        )

    print("\n=== DECISION TRAIL (authz_decisions) — every allow/deny ===")
    for d in audit.read_decisions(limit=20):
        m = d.get("metadata", {})
        print(
            f"  {d['actor'] or '-':>6}  {d['action']:<14} {d['target']:<28} required={m.get('required')}"
        )

    print(
        "\nBoth tables are INSERT-only. token references are jti/short-hash, never the raw token."
    )


if __name__ == "__main__":
    import os

    os.makedirs("tmp", exist_ok=True)
    main()
