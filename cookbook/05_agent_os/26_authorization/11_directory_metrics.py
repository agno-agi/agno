"""
Metrics about the user directory: GET /metrics/users

Once an AgentOS has a user directory it also serves a small metrics endpoint about
that directory, computed live on every read (no cache, no refresh step):

    users          total / active / disabled, and how many hold no role
    users_created  users created per UTC day (a line chart)
    users_by_role  users per role, when a role store is configured

The counts are the directory as it is now: deleting a user moves every number at
once. Reading them needs the metrics:read scope, the same one the run metrics use.

This example seeds a directory and a role store, then reads the endpoint through
the AgentOS pipeline with an admin token and prints the response. No model calls
and no database server are needed.

Run it:
    pip install "agno[roles]"
    python 11_directory_metrics.py
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

OS_ID = "directory-metrics-os"
SECRET = "your-secret-key-at-least-256-bits-long"

os.makedirs("tmp", exist_ok=True)
for stale in ("tmp/directory_metrics.db",):
    if os.path.exists(stale):
        os.remove(stale)

db = SqliteDb(db_file="tmp/directory_metrics.db")
roles = ManagedRoleStore(db=db)
users = ManagedUserStore(db=db)

roles.set_role_scopes("admin", ["agent_os:admin"])
roles.set_role_scopes("analyst", ["agents:*:read", "metrics:read"])
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
        role_store=roles,  # auto-mounts /authz, /users and /metrics/users
    ),
    user_directory=UserDirectoryConfig(user_store=users),
)
app = agent_os.get_app()


if __name__ == "__main__":
    from fastapi.testclient import TestClient

    client = TestClient(app)

    def auth(sub: str, scopes=()):
        token = create_dev_token(
            sub, secret=SECRET, audience=OS_ID, scopes=list(scopes)
        )
        return {"Authorization": f"Bearer {token}"}

    print("\n" + "=" * 78)
    print("USER DIRECTORY METRICS - GET /metrics/users")
    print("=" * 78)

    # The role decides. alice is admin (agent_os:admin covers metrics:read); erin has
    # no role, so her token is refused even though she is in the directory.
    print(
        "\nerin (no role):  ",
        client.get("/metrics/users", headers=auth("erin")).status_code,
        "(expected 403)",
    )
    print(
        "bob (analyst):   ",
        client.get("/metrics/users", headers=auth("bob")).status_code,
        "(expected 200)",
    )

    response = client.get("/metrics/users", headers=auth("alice"))
    print("alice (admin):   ", response.status_code, "(expected 200)")
    print("\n" + json.dumps(response.json(), indent=2))

    # The date range bounds the series only; the counts stay whole-directory.
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    bounded = client.get(
        f"/metrics/users?starting_date={today}", headers=auth("alice")
    ).json()
    print(
        "\nSeries from today only:",
        bounded["users_created"],
        "with total still",
        bounded["users"]["total"],
    )

    # No refresh step: deleting a user moves every number on the next read.
    client.delete("/users/carol", headers=auth("alice"))
    after = client.get("/metrics/users", headers=auth("alice")).json()
    print(
        "After deleting carol:  total",
        after["users"]["total"],
        "by role",
        after["users_by_role"],
    )
