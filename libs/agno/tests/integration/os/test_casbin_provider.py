"""CasbinAuthorizationProvider: the optional Casbin-backed authz provider.

Proves it (a) implements the provider interface, (b) makes correct role +
hierarchy + wildcard decisions via a real casbin.Enforcer, and (c) gates a real
AgentOS end to end behind the provider seam. Default provider is unchanged.

Skipped automatically if casbin isn't installed (it's an opt-in extra).
"""

from datetime import timedelta

import pytest

pytest.importorskip("casbin")  # opt-in extra; skip if not installed

import casbin  # noqa: E402
import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agno.agent.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz import AuthorizationContext  # noqa: E402
from agno.os.authz.casbin_provider import CasbinAuthorizationProvider  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402

SECRET = "casbin-provider-secret-long-enough-for-hs256-validation"
OS_ID = "casbin-os"

MODEL = """
[request_definition]
r = sub, obj, act
[policy_definition]
p = sub, obj, act
[role_definition]
g = _, _
[policy_effect]
e = some(where (p.eft == allow))
[matchers]
m = g(r.sub, p.sub) && keyMatch2(r.obj, p.obj) && (r.act == p.act || p.act == "*")
"""

# member can read+run agents; admin inherits member and can do everything.
POLICY = """
p, member, agents/*, read
p, member, agents/research-agent, run
p, admin, agents/*, *
g, alice, member
g, root, admin
"""


def _enforcer(tmp_path):
    m = tmp_path / "m.conf"
    p = tmp_path / "p.csv"
    m.write_text(MODEL)
    p.write_text(POLICY)
    return casbin.Enforcer(str(m), str(p))


def _ctx(sub, rt, rid, act):
    return AuthorizationContext(principal_id=sub, resource_type=rt, resource_id=rid, action=act)


def test_check_decisions(tmp_path):
    prov = CasbinAuthorizationProvider(_enforcer(tmp_path))
    assert prov.check(_ctx("alice", "agents", "research-agent", "run")) is True
    assert prov.check(_ctx("alice", "agents", "research-agent", "read")) is True
    # alice (member) cannot run a different agent (only research-agent granted run)
    assert prov.check(_ctx("alice", "agents", "other-agent", "run")) is False
    # root (admin, via g + wildcard) can do anything
    assert prov.check(_ctx("root", "agents", "any-agent", "run")) is True
    # unknown subject -> deny
    assert prov.check(_ctx("mallory", "agents", "research-agent", "run")) is False


def test_non_resource_check_defers(tmp_path):
    prov = CasbinAuthorizationProvider(_enforcer(tmp_path))
    assert prov.check(AuthorizationContext(principal_id="alice")) is True  # no resource -> allow


def test_accessible_resource_ids(tmp_path):
    prov = CasbinAuthorizationProvider(_enforcer(tmp_path))
    # alice has agents/* read -> wildcard
    assert prov.accessible_resource_ids(_ctx("alice", "agents", None, "read")) == {"*"}
    # for run, alice only has the specific research-agent
    assert prov.accessible_resource_ids(_ctx("alice", "agents", None, "run")) == {"research-agent"}


def test_bad_enforcer_type():
    with pytest.raises(TypeError):
        CasbinAuthorizationProvider(object())


def test_roles_from_token_claim_idp_case(tmp_path):
    """Users WITH an IdP: roles come off the token, no stored g assignment."""
    prov = CasbinAuthorizationProvider(_enforcer(tmp_path), roles_claim="roles")
    # idp-user has no g assignment in the policy, but the token carries member.
    ctx = AuthorizationContext(
        principal_id="auth0|xyz", resource_type="agents", resource_id="research-agent",
        action="run", claims={"roles": ["member"]},
    )
    assert prov.check(ctx) is True
    # a role the policy doesn't grant -> denied
    ctx_guest = AuthorizationContext(
        principal_id="auth0|xyz", resource_type="agents", resource_id="research-agent",
        action="run", claims={"roles": ["guest"]},
    )
    assert prov.check(ctx_guest) is False


def test_roles_from_token_claim_single_string(tmp_path):
    """WorkOS sends a single `role` string (not a list); it must still authorize."""
    prov = CasbinAuthorizationProvider(_enforcer(tmp_path), roles_claim="role")
    ctx = AuthorizationContext(
        principal_id="workos|abc", resource_type="agents", resource_id="research-agent",
        action="run", claims={"role": "member"},  # a bare string, not ["member"]
    )
    assert prov.check(ctx) is True
    ctx_guest = AuthorizationContext(
        principal_id="workos|abc", resource_type="agents", resource_id="research-agent",
        action="run", claims={"role": "guest"},
    )
    assert prov.check(ctx_guest) is False


def test_enforce_only_no_store_assignments(tmp_path):
    """Scenario 1: roles come from the token, the policy has only role definitions
    (no `g` user->role rows). Authorization still works with no per-user store."""
    import casbin

    m = tmp_path / "m.conf"
    p = tmp_path / "p.csv"
    m.write_text(MODEL)
    p.write_text("p, member, agents/*, read\np, member, agents/research-agent, run\n")  # no g rows
    prov = CasbinAuthorizationProvider(casbin.Enforcer(str(m), str(p)), roles_claim="role")

    allowed = AuthorizationContext(
        principal_id="anyone", resource_type="agents", resource_id="research-agent",
        action="run", claims={"role": "member"},
    )
    denied = AuthorizationContext(
        principal_id="anyone", resource_type="agents", resource_id="research-agent",
        action="run", claims={},  # no role on the token -> nothing to fall back to
    )
    assert prov.check(allowed) is True
    assert prov.check(denied) is False


def test_roles_from_store_when_no_claim(tmp_path):
    """Users WITHOUT an IdP: no roles claim -> fall back to Casbin's g store."""
    prov = CasbinAuthorizationProvider(_enforcer(tmp_path), roles_claim="roles")
    # alice has g, alice, member in the store; token carries no roles claim.
    ctx = AuthorizationContext(
        principal_id="alice", resource_type="agents", resource_id="research-agent",
        action="run", claims={},
    )
    assert prov.check(ctx) is True


def test_end_to_end_agentos_uses_casbin(tmp_path):
    agent = Agent(id="research-agent", name="Research Agent", db=InMemoryDb())
    agent.deep_copy = lambda **_: agent
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=CasbinAuthorizationProvider(_enforcer(tmp_path)),
        ),
    )
    client = TestClient(agent_os.get_app())

    def token(sub):
        return {"Authorization": "Bearer " + jwt.encode(
            {"sub": sub, "aud": OS_ID, "scopes": [],
             "exp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc) + timedelta(minutes=5)},
            SECRET, algorithm="HS256")}

    # alice (member) may run research-agent; mallory (no role) may not.
    assert client.post("/agents/research-agent/runs", headers=token("alice"), data={"message": "hi"}).status_code == 200
    assert client.post("/agents/research-agent/runs", headers=token("mallory"), data={"message": "hi"}).status_code == 403
