"""
Per-user knowledge ownership
============================

With AuthorizationConfig(user_isolation=True) every uploaded content row is
stamped with the JWT subject. A non-admin reads their own rows plus the shared
(unowned) org-wide rows, but may only modify or delete the rows they own. The
smoke proves the read scope, the 403 on shared content, the 404 on another
user's content, and the admin bypass.

Prerequisites: none
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/user_isolation_knowledge.py
Try: call DELETE /knowledge/content as alice and watch the shared row survive
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from agno.agent import Agent
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create an isolated AgentOS
# ---------------------------------------------------------------------------

OS_ID = "knowledge-isolation-security-demo"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY", "development-secret-at-least-256-bits-long"
)

db = SqliteDb(db_file="tmp/security_user_isolation_knowledge.db")
handbook = Knowledge(name="handbook", contents_db=db)
knowledge_agent = Agent(
    id="knowledge-agent",
    name="Knowledge Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    knowledge=handbook,
)
agent_os = AgentOS(
    id=OS_ID,
    agents=[knowledge_agent],
    knowledge=[handbook],
    db=db,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
        user_isolation=True,
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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed(content_id: str, name: str, owner: str | None) -> None:
    """Write one content row. ``owner=None`` is shared, org-wide content.

    The ingest pipeline needs a vector db and an embedder; this smoke is about
    the ownership rules the routes apply on top of the rows, so it writes them
    straight to the contents db.
    """
    db.upsert_knowledge_content(
        KnowledgeRow(
            id=content_id,
            name=name,
            description="user isolation smoke",
            user_id=owner,
            linked_to=handbook.name,
        )
    )


def run_smoke() -> dict[str, object]:
    suffix = uuid4().hex[:8]
    shared_id = f"handbook-{suffix}"
    alice_id = f"alice-notes-{suffix}"
    bob_id = f"bob-notes-{suffix}"
    alice_user = f"alice-{suffix}"
    bob_user = f"bob-{suffix}"
    user_scopes = ["knowledge:read", "knowledge:write", "knowledge:delete"]
    alice = make_token(alice_user, user_scopes)
    admin = make_token("security-admin", ["agent_os:admin"])

    _seed(shared_id, "Company handbook", None)
    _seed(alice_id, "Alice notes", alice_user)
    _seed(bob_id, "Bob notes", bob_user)

    with TestClient(app) as client:
        alice_rows = client.get("/knowledge/content", headers=_auth(alice)).json()[
            "data"
        ]
        patch_shared = client.patch(
            f"/knowledge/content/{shared_id}",
            data={"name": "Rewritten handbook"},
            headers=_auth(alice),
        )
        delete_shared = client.delete(
            f"/knowledge/content/{shared_id}", headers=_auth(alice)
        )
        delete_bob = client.delete(f"/knowledge/content/{bob_id}", headers=_auth(alice))
        bulk_delete = client.delete("/knowledge/content", headers=_auth(alice))
        after_bulk = client.get("/knowledge/content", headers=_auth(alice)).json()[
            "data"
        ]
        admin_delete_shared = client.delete(
            f"/knowledge/content/{shared_id}", headers=_auth(admin)
        )

    # A non-admin sees their own rows plus the shared one, never another user's.
    assert {row["name"] for row in alice_rows} == {"Company handbook", "Alice notes"}
    # Shared content is readable but not writable by a scoped caller.
    assert patch_shared.status_code == 403, patch_shared.text
    assert delete_shared.status_code == 403, delete_shared.text
    # Another user's row is invisible, so it reads as missing rather than denied.
    assert delete_bob.status_code == 404, delete_bob.text
    # A bulk delete clears the caller's own rows and spares the shared one.
    assert bulk_delete.status_code == 200, bulk_delete.text
    assert {row["name"] for row in after_bulk} == {"Company handbook"}
    # Removing shared content is the admin path.
    assert admin_delete_shared.status_code == 200, admin_delete_shared.text
    return {
        "alice_visible": [row["name"] for row in alice_rows],
        "patch_shared": patch_shared.status_code,
        "delete_shared": delete_shared.status_code,
        "delete_other_user": delete_bob.status_code,
        "after_bulk_delete": [row["name"] for row in after_bulk],
        "admin_delete_shared": admin_delete_shared.status_code,
    }


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    isolation_result = run_smoke()
    print("Per-user knowledge ownership smoke passed:")
    print(isolation_result)
    agent_os.serve(app=app, port=7777)
