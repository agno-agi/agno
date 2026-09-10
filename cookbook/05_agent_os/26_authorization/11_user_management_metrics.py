"""
User management metrics: GET /users/metrics

The users admin API also serves the numbers a User Management page shows about the
directory, computed live on every read (no cache, no refresh step):

    total / active / disabled   the directory as it is now, plus without_role
    created_per_day             users created per UTC day (a line chart)
    by_role                     users per role, when a role store is configured

It rides on the same router as /users, so it is admin-only and appears wherever
user management appears: auto-mounted with a role store, or mounted by you with
get_users_router(...) in a users-only setup (see 07_manage_users.py). Deleting a
user moves every number at once.

This example seeds a directory and a role store, then reads the endpoint through
the AgentOS pipeline with an admin token and prints the response. No model calls
and no database server are needed.

Run it:
    pip install "agno[roles]"
    python 11_user_management_metrics.py
"""

import json
import os
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, create_dev_token
from agno.os.authz import ManagedRoleStore, ManagedUserStore
from agno.os.config import AuthorizationConfig, UserDirectoryConfig

OS_ID = "user-management-metrics-os"
SECRET = "your-secret-key-at-least-256-bits-long"

os.makedirs("tmp", exist_ok=True)
for stale in ("tmp/user_management_metrics.db",):
    if os.path.exists(stale):
        os.remove(stale)

db = SqliteDb(db_file="tmp/user_management_metrics.db")
roles = ManagedRoleStore(db=db)
users = ManagedUserStore(db=db)

roles.set_role_scopes("admin", ["agent_os:admin"])
roles.set_role_scopes("analyst", ["agents:*:read"])
roles.set_role_scopes("viewer", ["agents:*:read"])

# A small directory: an admin, two analysts, one viewer, one person with no role yet,
# and one who has been switched off. Backdate two of them so the per-day series has
# more than one point.
day = 24 * 60 * 60
now = int(time.time())
users.upsert("alice", email="alice@co", name="Alice")
users.upsert("bob", email="bob@co", name="Bob")
users.upsert("carol", email="carol@co", name="Carol")
users.upsert("dave", email="dave@co", name="Dave")
users.upsert("erin", email="erin@co", name="Erin")
users.upsert("frank", email="frank@co", name="Frank")
for user_id, created_at in (
    ("bob", now - 3 * day),
    ("carol", now - 3 * day),
    ("dave", now - day),
):
    row = {**users.get(user_id), "created_at": created_at}
    db.upsert_authz_user(user_id, {k: v for k, v in row.items() if k != "id"})
roles.assign("alice", "admin")
roles.assign("bob", "analyst")
roles.assign("carol", "analyst")
roles.assign("dave", "viewer")
users.set_disabled("frank", True)

agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

agent_os = AgentOS(
    id=OS_ID,
    db=db,
    agents=[agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        role_store=roles,  # auto-mounts /authz and /users (with /users/metrics)
    ),
    user_directory=UserDirectoryConfig(user_store=users),
)
app = agent_os.get_app()


if __name__ == "__main__":
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient

    client = TestClient(app)

    def auth(sub: str, scopes=()):
        token = create_dev_token(
            sub, secret=SECRET, audience=OS_ID, scopes=list(scopes)
        )
        return {"Authorization": f"Bearer {token}"}

    print("\n" + "=" * 78)
    print("USER MANAGEMENT METRICS - GET /users/metrics")
    print("=" * 78)

    # Admin-only, like the rest of /users: bob is an analyst, not an admin, so he is
    # refused even though he is in the directory.
    bob = client.get("/users/metrics", headers=auth("bob")).status_code
    response = client.get("/users/metrics", headers=auth("alice"))
    print("\nbob (analyst):   ", bob, "(expected 403)")
    print("alice (admin):   ", response.status_code, "(expected 200)")
    print("\n" + json.dumps(response.json(), indent=2))

    # The date range bounds the series only; the counts stay whole-directory.
    today = datetime.now(timezone.utc).date().isoformat()
    bounded = client.get(
        f"/users/metrics?starting_date={today}", headers=auth("alice")
    ).json()
    print(
        "\nSeries from today only:",
        bounded["created_per_day"],
        "with total still",
        bounded["total"],
    )

    # No refresh step: deleting a user moves every number on the next read.
    client.delete("/users/carol", headers=auth("alice"))
    after = client.get("/users/metrics", headers=auth("alice")).json()
    print("After deleting carol:  total", after["total"], "by role", after["by_role"])
