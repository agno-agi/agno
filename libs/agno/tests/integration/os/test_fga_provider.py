"""Fine-grained / relationship-based authorization via the FGA provider.

Proves the provider maps AgentOS authorization to relationship queries (Check /
ListObjects) correctly, and gates a real AgentOS end-to-end when composed with
the scope provider — all against an in-memory FGA store, so no OpenFGA server is
needed. The same provider runs against real OpenFGA / WorkOS FGA by swapping the
client (see OpenFGAClient).
"""

from datetime import UTC, datetime, timedelta
from typing import List, Set, Tuple

import jwt
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.authz import AuthorizationContext, FGAAuthorizationProvider, ScopeAuthorizationProvider
from agno.os.config import AuthorizationConfig

SECRET = "fga-provider-test-secret-at-least-256-bits-long-xxxxxx"
OS_ID = "fga-test-os"


class InMemoryFGA:
    """A toy FGAClient: a set of (user, relation, object) relationship tuples.
    Stands in for OpenFGA/WorkOS FGA so the tests need no external engine."""

    def __init__(self, tuples: Set[Tuple[str, str, str]]):
        self._tuples = set(tuples)

    def check(self, user: str, relation: str, obj: str) -> bool:
        return (user, relation, obj) in self._tuples

    def list_objects(self, user: str, relation: str, object_type: str) -> List[str]:
        return [o for (u, r, o) in self._tuples if u == user and r == relation and o.startswith(f"{object_type}:")]


def _ctx(sub, rt, rid, act):
    return AuthorizationContext(principal_id=sub, resource_type=rt, resource_id=rid, action=act)


# ----------------------------------------------------------------- provider unit
def test_check_maps_to_a_relationship_query():
    fga = InMemoryFGA({("user:alice", "run", "workflows:wf-7")})
    prov = FGAAuthorizationProvider(fga)
    assert prov.check(_ctx("alice", "workflows", "wf-7", "run")) is True
    # different object, different relation, different user -> denied
    assert prov.check(_ctx("alice", "workflows", "wf-8", "run")) is False
    assert prov.check(_ctx("alice", "workflows", "wf-7", "read")) is False
    assert prov.check(_ctx("bob", "workflows", "wf-7", "run")) is False
    # unauthenticated principal -> denied on a resource check
    assert prov.check(_ctx(None, "workflows", "wf-7", "run")) is False


def test_accessible_ids_maps_to_list_objects():
    fga = InMemoryFGA({
        ("user:alice", "read", "agents:a1"),
        ("user:alice", "read", "agents:a2"),
        ("user:alice", "run", "agents:a1"),  # different relation, excluded for read
        ("user:bob", "read", "agents:a3"),
    })
    prov = FGAAuthorizationProvider(fga)
    assert prov.accessible_resource_ids(_ctx("alice", "agents", None, "read")) == {"a1", "a2"}
    assert prov.accessible_resource_ids(_ctx("alice", "agents", None, "run")) == {"a1"}
    assert prov.accessible_resource_ids(_ctx("bob", "agents", None, "read")) == {"a3"}
    assert prov.accessible_resource_ids(_ctx("nobody", "agents", None, "read")) == set()


def test_list_endpoint_defers_to_accessible_ids():
    # No resource_id => a listing: check() allows so the handler runs, and
    # accessible_resource_ids narrows the result.
    prov = FGAAuthorizationProvider(InMemoryFGA(set()))
    assert prov.check(_ctx("alice", "agents", None, "read")) is True


def test_custom_user_type_and_relation_map():
    fga = InMemoryFGA({("account:alice", "can_execute", "agents:a1")})
    prov = FGAAuthorizationProvider(fga, user_type="account", relation_map={"run": "can_execute"})
    assert prov.check(_ctx("alice", "agents", "a1", "run")) is True


def test_authorize_route_abstains_on_non_resource_routes():
    """FGA can't express /config or /sessions as a single object, so it must
    ABSTAIN (False) there — never fail-open when OR-composed with a scope provider."""
    prov = FGAAuthorizationProvider(InMemoryFGA({("user:alice", "run", "agents:a1")}))
    # resource route -> relational decision
    assert prov.authorize_route(_ctx("alice", "agents", "a1", "run"), ["agents:run"]) is True
    # non-resource route -> abstain (a composed scope provider authorizes these)
    assert prov.authorize_route(AuthorizationContext(principal_id="alice"), ["config:read"]) is False


# ----------------------------------------------------------------- end to end
def _token(sub: str) -> str:
    return jwt.encode(
        {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET, algorithm="HS256",
    )


def _auth(sub: str) -> dict:
    return {"Authorization": f"Bearer {_token(sub)}"}


def test_fga_gates_a_real_agentos_per_resource():
    """End to end: relationships in the FGA store decide who can run which agent,
    with FGA composed alongside the scope provider on one OS."""
    fga = InMemoryFGA({
        ("user:alice", "run", "agents:research-agent"),   # alice may run research-agent
        ("user:alice", "read", "agents:research-agent"),
    })
    research = Agent(id="research-agent", name="Research Agent", db=InMemoryDb())
    other = Agent(id="other-agent", name="Other Agent", db=InMemoryDb())
    agent_os = AgentOS(
        id=OS_ID,
        agents=[research, other],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            # ReBAC for resources (alice's relationships) + scopes for everything else.
            authorization_provider=[ScopeAuthorizationProvider(), FGAAuthorizationProvider(fga)],
        ),
    )
    client = TestClient(agent_os.get_app())

    # alice is related (run) to research-agent -> allowed
    r = client.post("/agents/research-agent/runs", headers=_auth("alice"), data={"message": "hi"})
    assert r.status_code != 403
    # alice has no relationship to other-agent -> denied
    r = client.post("/agents/other-agent/runs", headers=_auth("alice"), data={"message": "hi"})
    assert r.status_code == 403
    # bob has no relationships at all -> denied
    r = client.post("/agents/research-agent/runs", headers=_auth("bob"), data={"message": "hi"})
    assert r.status_code == 403
    # alice can read research-agent (relationship exists)
    assert client.get("/agents/research-agent", headers=_auth("alice")).status_code == 200
