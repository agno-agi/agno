"""
Custom PolicyEngine - keep managed roles and the /authz admin API, swap the backend

(New to this? Read 01_managed_roles.py first. If you want to replace the DECISION MODEL itself,
not just where policy is stored, see 12_custom_authorization_provider.py.)

Managed roles are two layers:

  - the Authorization object and the /authz admin API: define_role, assign, seed, audit,
    the runtime role API, the admin routes a frontend drives;
  - a PolicyEngine underneath: where role -> scopes and subject -> roles are stored, and
    who answers "may this identity do this?".

The default engine keeps policy in your SQL database. `Authorization(engine=...)` swaps ONLY
that layer: hand it any PolicyEngine and everything above it stays, including the admin API
and the audit trail. That is the seam for OpenFGA, SpiceDB, a policy service you already run,
or, as here, a plain in-process dict so the contract is easy to read.

A PolicyEngine implements about a dozen methods in agno terms (see the ABC's docstrings):

  authoring     set_role_scopes / add_scope / remove_scope / get_role_scopes / remove_role / list_roles
  assignments   assign / unassign / roles_of  (+ subjects_of, so the admin-lockout check can run)
  decisions     check_scope / check_resource / accessible_resource_ids

Identity arrives two ways: `subject` (resolve its stored assignments: the no-IdP case) or
`roles` (already on the token, via roles_claim: the IdP case). When `roles` is given it wins.
The async variants have defaults that run your sync methods in a worker thread, so a sync
engine works on the async request path as is.

Role METADATA (display name, description, the default role) is not policy, so agno keeps it in
the bound database next to the engine; the OS db is enough for that.

Run it:
    pip install "agno[os]"
    python 14_custom_policy_engine.py
(no external services and no model key: it decides who is allowed, without calling a model.)
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Dict, List, Optional, Set

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization
from agno.os.authz import PolicyEngine

JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "custom-engine-os"

os.makedirs("tmp", exist_ok=True)
if os.path.exists("tmp/custom_engine.db"):
    os.remove("tmp/custom_engine.db")


# ---------------------------------------------------------------------------
# The whole integration: implement the PolicyEngine ABC.
# ---------------------------------------------------------------------------


def _matches(pattern: str, scope: str) -> bool:
    """'agents:*:read' matches 'agents:research-agent:read'. A two-part pattern such as
    'agents:read' covers the collection and every member."""
    p, s = pattern.split(":"), scope.split(":")
    if len(p) == 2 and len(s) == 3:
        p = [p[0], "*", p[1]]
    return len(p) == len(s) and all(a == "*" or a == b for a, b in zip(p, s))


class DictPolicyEngine(PolicyEngine):
    """Policy in two dicts. Replace the bodies with calls to your own service."""

    def __init__(self) -> None:
        self.policies: Dict[
            str, Dict[str, str]
        ] = {}  # role -> {scope: "allow" | "deny"}
        self.assignments: Dict[str, Set[str]] = {}  # subject -> {role}

    # --- authoring: roles -> scopes (what define_role / the admin API write) ---
    def set_role_scopes(self, role: str, entries) -> None:
        self.policies[role] = {scope: effect for scope, effect in entries}

    def add_scope(self, role: str, scope: str, effect: str = "allow") -> None:
        self.policies.setdefault(role, {})[scope] = effect

    def remove_scope(self, role: str, scope: str) -> None:
        self.policies.get(role, {}).pop(scope, None)

    def get_role_scopes(self, role: str):
        return list(self.policies.get(role, {}).items())

    def remove_role(self, role: str) -> None:
        self.policies.pop(role, None)
        for roles in self.assignments.values():
            roles.discard(role)

    def list_roles(self) -> List[str]:
        return sorted(self.policies)

    # --- assignments: subject -> roles (what assign / seed / the admin API write) ---
    def assign(self, subject: str, role: str) -> None:
        self.assignments.setdefault(subject, set()).add(role)

    def unassign(self, subject: str, role: str) -> None:
        self.assignments.get(subject, set()).discard(role)

    def roles_of(self, subject: str) -> List[str]:
        return sorted(self.assignments.get(subject, ()))

    def subjects_of(self, role: str) -> List[str]:
        return sorted(s for s, roles in self.assignments.items() if role in roles)

    # --- decisions ---
    def _effective_roles(
        self, subject: Optional[str], roles: Optional[List[str]]
    ) -> List[str]:
        # roles on the token win; otherwise the subject's stored assignments decide
        return roles if roles is not None else self.roles_of(subject or "")

    def _decide(
        self, scope: str, subject: Optional[str], roles: Optional[List[str]]
    ) -> bool:
        allowed = False
        for role in self._effective_roles(subject, roles):
            for pattern, effect in self.policies.get(role, {}).items():
                if _matches(pattern, scope):
                    if effect == "deny":
                        return False  # deny overrides any allow
                    allowed = True
        return allowed

    def check_scope(self, scope: str, *, subject=None, roles=None) -> bool:
        return self._decide(scope, subject, roles)

    def check_resource(
        self, resource_type, resource_id, action, *, subject=None, roles=None
    ) -> bool:
        if not resource_type or not action:
            return True  # a non-resource question is the route gate's (check_scope), not a denial
        scope = (
            f"{resource_type}:{resource_id}:{action}"
            if resource_id
            else f"{resource_type}:{action}"
        )
        return self._decide(scope, subject, roles)

    def accessible_resource_ids(
        self, resource_type, action, *, subject=None, roles=None
    ) -> Set[str]:
        # For list endpoints: the ids of resource_type this identity may see ({"*"} = all).
        ids: Set[str] = set()
        for role in self._effective_roles(subject, roles):
            for pattern, effect in self.policies.get(role, {}).items():
                parts = pattern.split(":")
                if effect != "allow" or parts[0] != resource_type:
                    continue
                wanted = (action, "*") if action else None
                if len(parts) == 2 and (wanted is None or parts[1] in wanted):
                    return {"*"}
                if len(parts) == 3 and (wanted is None or parts[2] in wanted):
                    if parts[1] == "*":
                        return {"*"}
                    ids.add(parts[1])
        return ids


# ---------------------------------------------------------------------------
# Wire it in: Authorization(engine=<your engine>). Everything else is 01_managed_roles.py.
# ---------------------------------------------------------------------------

engine = DictPolicyEngine()
db = SqliteDb(
    db_file="tmp/custom_engine.db"
)  # role metadata and the agent's data; policy is in the engine

authz = Authorization(
    engine=engine,  # <- the seam
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    verify_audience=True,
    audience=OS_ID,
)
# define_role / seed / assign land in YOUR engine (look at engine.policies afterwards).
authz.define_role("admin", ["agent_os:admin"], name="Administrator")
authz.define_role("member", ["agents:*:read", "agents:*:run"])
authz.define_role("viewer", ["agents:*:read"])
authz.seed(admin="alice")
authz.assign("bob", "member")
authz.assign("carol", "viewer")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
)

agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS whose role policy lives in a custom engine",
    agents=[research_agent],
    db=db,  # the object borrows this for role metadata; the engine holds the policy
    authorization=authz,
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging

    from fastapi.testclient import TestClient

    logging.disable(logging.CRITICAL)
    client = TestClient(app)

    def token(sub: str) -> str:
        return jwt.encode(
            {
                "sub": sub,
                "aud": OS_ID,
                "scopes": [],
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            JWT_SECRET,
            algorithm="HS256",
        )

    def show(
        label: str, sub: str, method: str, path: str, note: str = "", **kw
    ) -> None:
        r = client.request(
            method, path, headers={"Authorization": f"Bearer {token(sub)}"}, **kw
        )
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:40s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 80)
    print("CUSTOM POLICY ENGINE - the roles live in your engine, agno runs the rest")
    print("=" * 80)
    print("  what the engine holds after define_role / seed / assign:")
    for role in engine.list_roles():
        print(f"    {role:8s} {engine.get_role_scopes(role)}")
    print(
        f"    assignments: {dict(sorted((s, sorted(r)) for s, r in engine.assignments.items()))}\n"
    )

    show(
        "bob   (member) RUN the agent",
        "bob",
        "POST",
        "/agents/research-agent/runs",
        "members can run",
        data={"message": "hi"},
    )
    show(
        "carol (viewer) LOOK at agent",
        "carol",
        "GET",
        "/agents/research-agent",
        "viewers can read",
    )
    show(
        "carol (viewer) RUN the agent",
        "carol",
        "POST",
        "/agents/research-agent/runs",
        "viewers can't run -> bounced",
        data={"message": "hi"},
    )
    show(
        "dave  (no role) LOOK at agent",
        "dave",
        "GET",
        "/agents/research-agent",
        "unknown -> bounced",
    )

    # The admin API works on top of the custom engine: an admin edits a role at runtime and the
    # engine sees the change immediately.
    show(
        "alice (admin) LIST /authz/roles",
        "alice",
        "GET",
        "/authz/roles",
        "the admin API, backed by the engine",
    )
    r = client.put(
        "/authz/roles/viewer/scopes",
        headers={"Authorization": f"Bearer {token('alice')}"},
        json={"scopes": ["agents:*:read", "agents:*:run"]},
    )
    print(
        f"  alice widens viewer via PUT /authz/roles/viewer/scopes -> {r.status_code}; engine now says {engine.get_role_scopes('viewer')}"
    )
    show(
        "carol (viewer) RUN the agent",
        "carol",
        "POST",
        "/agents/research-agent/runs",
        "widened at runtime -> allowed",
        data={"message": "hi"},
    )

    print("=" * 80)
    print(
        "the point: Authorization(engine=...) swaps where policy lives and who decides."
    )
    print(
        "define_role, seed, assign, audit and the /authz admin API all keep working on top."
    )
    print("=" * 80)
