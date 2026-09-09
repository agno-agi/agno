"""
Per-user knowledge ownership
============================

Turn on AuthorizationConfig(user_isolation=True) so every knowledge content row
is owned by the JWT subject, and a row with no owner is shared, org-wide
content. The smoke proves the read scope, the 403 on shared content, the 404 on
another user's content, and the admin bypass. Rows are seeded straight into the
contents db because the ingest run by POST /knowledge/content has no vector db.

Prerequisites: none
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/user_isolation_knowledge.py
Try: send DELETE /knowledge/content with the printed alice token; the shared row survives
"""

import os
from datetime import UTC, datetime, timedelta

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
    """Write one content row; an owner of None is shared, org-wide content."""
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
    user_scopes = ["knowledge:read", "knowledge:write", "knowledge:delete"]
    alice = make_token("alice", user_scopes)
    admin = make_token("security-admin", ["agent_os:admin"])

    _seed("company-handbook", "Company handbook", None)
    _seed("retired-handbook", "Retired handbook", None)
    _seed("alice-notes", "Alice notes", "alice")
    _seed("bob-notes", "Bob notes", "bob")

    with TestClient(app) as client:
        alice_rows = client.get("/knowledge/content", headers=_auth(alice)).json()[
            "data"
        ]
        patch_shared = client.patch(
            "/knowledge/content/company-handbook",
            data={"name": "Rewritten handbook"},
            headers=_auth(alice),
        )
        delete_shared = client.delete(
            "/knowledge/content/company-handbook", headers=_auth(alice)
        )
        delete_bob = client.delete("/knowledge/content/bob-notes", headers=_auth(alice))
        bulk_delete = client.delete("/knowledge/content", headers=_auth(alice))
        after_bulk = client.get("/knowledge/content", headers=_auth(alice)).json()[
            "data"
        ]
        admin_delete_shared = client.delete(
            "/knowledge/content/retired-handbook", headers=_auth(admin)
        )
        admin_delete_bob = client.delete(
            "/knowledge/content/bob-notes", headers=_auth(admin)
        )

    assert {row["name"] for row in alice_rows} == {
        "Company handbook",
        "Retired handbook",
        "Alice notes",
    }
    assert patch_shared.status_code == 403, patch_shared.text
    assert delete_shared.status_code == 403, delete_shared.text
    assert delete_bob.status_code == 404, delete_bob.text
    assert bulk_delete.status_code == 200, bulk_delete.text
    assert {row["name"] for row in after_bulk} == {
        "Company handbook",
        "Retired handbook",
    }
    assert admin_delete_shared.status_code == 200, admin_delete_shared.text
    assert admin_delete_bob.status_code == 200, admin_delete_bob.text
    return {
        "alice_visible": sorted(row["name"] for row in alice_rows),
        "patch_shared": patch_shared.status_code,
        "delete_shared": delete_shared.status_code,
        "delete_other_user": delete_bob.status_code,
        "after_bulk_delete": sorted(row["name"] for row in after_bulk),
        "admin_delete_shared": admin_delete_shared.status_code,
        "admin_delete_other_user": admin_delete_bob.status_code,
    }


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    isolation_result = run_smoke()
    print("Per-user knowledge ownership smoke passed:")
    print(isolation_result)

    _seed("alice-notes", "Alice notes", "alice")
    print("\nServed content: the shared Company handbook and one row owned by alice.")
    print("Alice token (knowledge:read, knowledge:write, knowledge:delete):")
    print(
        make_token("alice", ["knowledge:read", "knowledge:write", "knowledge:delete"])
    )
    agent_os.serve(app=app, port=7777)
