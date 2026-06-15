"""Fine-grained / relationship-based authorization (ReBAC) for AgentOS.

RBAC says "what may a *role* do?". Sometimes that's not enough — you want "alice
may run *this* workflow because she *owns the folder it's in*", or "a member of
team-x may read the agents that belong to team-x". That's relationship-based
access control (ReBAC), the model behind OpenFGA / WorkOS FGA / Zanzibar.

AgentOS doesn't embed a relationship engine — it plugs one in through the same
`AuthorizationProvider` seam everything else uses. `FGAAuthorizationProvider`
turns each AgentOS check into one relationship query:

    can alice RUN agents:research-agent?  ->  fga.check("user:alice", "run", "agents:research-agent")
    which agents can alice READ?          ->  fga.list_objects("user:alice", "read", "agents")

Run this example:
    python fga_relationship_based.py

It uses a tiny in-memory relationship store so it runs with zero infra. For
production you swap that one object for OpenFGA (or WorkOS FGA) — see the bottom.

The idiomatic wiring composes TWO providers (a feature of AgentOS): FGA decides
the per-resource families (agents/teams/workflows) relationally, while the scope
provider gates everything else (config, sessions, ...) — because FGA has no
notion of a non-resource route. A request is allowed if either grants.
"""

from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.authz import FGAAuthorizationProvider, ScopeAuthorizationProvider
from agno.os.config import AuthorizationConfig

SECRET = "fga-cookbook-secret-at-least-256-bits-long-padding-xx"
OS_ID = "fga-cookbook-os"


# --- a toy relationship store (stands in for OpenFGA / WorkOS FGA) -----------
# Each entry is (user, relation, object) — exactly what an FGA engine stores.
# In a real OpenFGA model these would often be *derived* (e.g. "run" inherited
# from "owner of the parent folder"); here we list them directly so it runs with
# no server.
class InMemoryFGA:
    def __init__(self, tuples):
        self._tuples = set(tuples)

    def check(self, user, relation, obj):
        return (user, relation, obj) in self._tuples

    def list_objects(self, user, relation, object_type):
        return [o for (u, r, o) in self._tuples if u == user and r == relation and o.startswith(f"{object_type}:")]


fga = InMemoryFGA(
    {
        # alice owns the research agent — she can read and run it
        ("user:alice", "read", "agents:research-agent"),
        ("user:alice", "run", "agents:research-agent"),
        # bob can only read it
        ("user:bob", "read", "agents:research-agent"),
    }
)

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
        authorization_provider=[
            ScopeAuthorizationProvider(),       # coarse: gates non-resource routes by scope
            FGAAuthorizationProvider(fga),      # fine: per-resource agents/teams/workflows by relationship
        ],
    ),
)
app = agent_os.get_app()


def _token(sub):
    return jwt.encode(
        {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET, algorithm="HS256",
    )


def _auth(sub):
    return {"Authorization": f"Bearer {_token(sub)}"}


if __name__ == "__main__":
    client = TestClient(app)

    def show(who, what, resp):
        verdict = "DENIED" if resp.status_code in (401, 403) else f"OK ({resp.status_code})"
        print(f"  {who:6s} {what:32s} -> {verdict}")

    print("\nrelationships decide access (no roles, no scopes — just who is related to what):\n")
    show("alice", "GET  /agents/research-agent", client.get("/agents/research-agent", headers=_auth("alice")))
    show("alice", "POST .../runs (alice owns it)",
         client.post("/agents/research-agent/runs", headers=_auth("alice"), data={"message": "hi"}))
    show("bob", "GET  /agents/research-agent", client.get("/agents/research-agent", headers=_auth("bob")))
    show("bob", "POST .../runs (bob can only read)",
         client.post("/agents/research-agent/runs", headers=_auth("bob"), data={"message": "hi"}))
    show("carol", "GET  /agents/research-agent (no relationship)",
         client.get("/agents/research-agent", headers=_auth("carol")))
    print("\nalice owns it (read+run), bob can only read, carol has no relationship at all.\n")

# --- production: point at real OpenFGA --------------------------------------
# Swap the in-memory store for OpenFGA (pip install "agno[fga]"); the provider is
# unchanged. Your OpenFGA authorization model must define relations matching the
# agno actions you gate (read / run / write / delete) on the agents/teams/
# workflows object types — and is where you express inheritance like
# "run if owner of the parent folder".
#
#   from agno.os.authz.fga import OpenFGAClient
#
#   fga = OpenFGAClient(
#       api_url="http://localhost:8080",
#       store_id="<your-store-id>",
#       authorization_model_id="<your-model-id>",
#   )
#   ...authorization_provider=[ScopeAuthorizationProvider(), FGAAuthorizationProvider(fga)]
#
# WorkOS FGA (or SpiceDB, ...) works the same way — implement the two-method
# FGAClient port over their SDK and pass it to FGAAuthorizationProvider.
