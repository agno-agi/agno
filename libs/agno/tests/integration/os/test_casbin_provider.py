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


def test_accessible_resource_ids_honours_roles_from_token(tmp_path):
    """IdP case: roles come off the token (no stored g row for the subject). List
    filtering must enumerate the role's grants, else collection endpoints return
    empty for exactly the population the route gate allows."""
    prov = CasbinAuthorizationProvider(_enforcer(tmp_path), roles_claim="roles")
    read_ctx = AuthorizationContext(
        principal_id="auth0|xyz", resource_type="agents", resource_id=None,
        action="read", claims={"roles": ["member"]},
    )
    run_ctx = AuthorizationContext(
        principal_id="auth0|xyz", resource_type="agents", resource_id=None,
        action="run", claims={"roles": ["member"]},
    )
    assert prov.accessible_resource_ids(read_ctx) == {"*"}  # agents/* read
    assert prov.accessible_resource_ids(run_ctx) == {"research-agent"}
    # a role the policy doesn't grant -> nothing accessible
    guest_ctx = AuthorizationContext(
        principal_id="auth0|xyz", resource_type="agents", resource_id=None,
        action="read", claims={"roles": ["guest"]},
    )
    assert prov.accessible_resource_ids(guest_ctx) == set()


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


# ---------------------------------------------------------------------------
# Hardening: scope_to_obj_act + accessible_resource_ids edge cases
# ---------------------------------------------------------------------------

from agno.os.authz.casbin_provider import scope_to_obj_act  # noqa: E402


class _FakeEnforcer:
    """Minimal enforcer stand-in to feed accessible_resource_ids exact policy rows
    (including malformed ones the real management API wouldn't normally produce)."""

    def __init__(self, perms):
        self._perms = perms

    def enforce(self, *args):  # provider __init__ only checks this attr exists
        return False

    def get_implicit_permissions_for_user(self, sub):
        return self._perms


def test_accessible_ids_ignores_malformed_policy_rows():
    """A policy row missing its action column must NOT grant ids. Previously a
    None action was treated as 'matches any action' — a fail-open."""
    fake = _FakeEnforcer(
        [
            ["alice", "agents/secret"],  # malformed: no action -> must be ignored
            ["alice", "agents/secret2", None],  # explicit None action -> ignored
            ["alice", "agents/ok", "read"],  # well-formed
        ]
    )
    prov = CasbinAuthorizationProvider(fake)
    ids = prov.accessible_resource_ids(_ctx("alice", "agents", None, "read"))
    assert ids == {"ok"}, f"malformed rows leaked ids: {ids}"


def test_accessible_ids_honours_action_and_wildcard():
    fake = _FakeEnforcer(
        [
            ["alice", "agents/a1", "read"],
            ["alice", "agents/a2", "run"],
            ["alice", "teams/t1", "*"],  # action wildcard (e.g. admin-style row)
        ]
    )
    prov = CasbinAuthorizationProvider(fake)
    assert prov.accessible_resource_ids(_ctx("alice", "agents", None, "read")) == {"a1"}
    assert prov.accessible_resource_ids(_ctx("alice", "agents", None, "run")) == {"a2"}
    # '*' action row matches any requested action
    assert prov.accessible_resource_ids(_ctx("alice", "teams", None, "read")) == {"t1"}


def test_scope_to_obj_act_valid_forms():
    assert scope_to_obj_act("agent_os:admin") == ("*", "*")
    assert scope_to_obj_act("sessions:write") == ("sessions/*", "write")
    assert scope_to_obj_act("agents:research-agent:run") == ("agents/research-agent", "run")
    assert scope_to_obj_act("agents:*:run") == ("agents/*", "run")  # resource-id wildcard is fine


def test_scope_to_obj_act_rejects_action_wildcard():
    """Action '*' would mean all-actions in Casbin but nothing in the scope
    provider; refuse it so managed roles can't carry a divergent broad grant."""
    for junk in ("agents:*:*", "agents:research-agent:*", "agents:*"):
        with pytest.raises(ValueError, match="wildcard"):
            scope_to_obj_act(junk)


def test_scope_to_obj_act_rejects_empty_components():
    for junk in (":read", "agents:", ":", "agents::run"):
        with pytest.raises(ValueError):
            scope_to_obj_act(junk)
