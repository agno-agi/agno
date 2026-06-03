"""Managed roles for AgentOS — agno-native API, Casbin hidden inside.

This is the "governance product" middle tier: create roles, assign them, and
change them at runtime, persisted to your own DB. You work entirely in agno
scope terms (``agents:*:read``, ``agents:research-agent:run``,
``agent_os:admin``); you never write a Casbin model or policy. Casbin + a DB
adapter is the engine under the hood (so changes persist and take effect on the
next request, no token re-mint), but it is an implementation detail.

Requires the optional extra: ``pip install "agno[casbin]"``.

Example::

    store = ManagedRoleStore(db_url="postgresql+psycopg://...", roles_claim="roles")
    store.set_role_scopes("member", ["agents:*:read", "agents:research-agent:run"])
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.assign("bob", "member")           # runtime, persisted

    agent_os = AgentOS(
        agents=[...],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[...],
            authorization_provider=store.provider,   # plug it in
        ),
    )

    # later, live (no redeploy, same token):
    store.assign("carol", "member")
    store.unassign("bob", "member")
"""

from typing import Any, Dict, List, Optional

from agno.os.authz.casbin_provider import scope_to_obj_act

_MODEL_TEXT = """
[request_definition]
r = sub, obj, act
[policy_definition]
p = sub, obj, act
[role_definition]
g = _, _
[policy_effect]
e = some(where (p.eft == allow))
[matchers]
m = g(r.sub, p.sub) && (p.obj == "*" || keyMatch2(r.obj, p.obj)) && (p.act == "*" || r.act == p.act)
"""


def _obj_act_to_scope(obj: str, act: str) -> str:
    """Best-effort reverse of :func:`scope_to_obj_act`, for display/read-back.

    Lossy where two scope spellings collapse to the same policy (``agents:read``
    and ``agents:*:read`` both store as ``("agents/*", "read")``); we render the
    global ``resource:action`` form in that case.
    """
    if obj == "*":
        return "agent_os:admin"
    if obj.endswith("/*"):
        return f"{obj[:-2]}:{act}"
    resource, _, rid = obj.partition("/")
    return f"{resource}:{rid}:{act}"


class ManagedRoleStore:
    """Runtime-mutable, persisted role store. agno-native in, Casbin hidden."""

    def __init__(self, db_url: Optional[str] = None, roles_claim: Optional[str] = None):
        """
        Args:
            db_url: SQLAlchemy URL for the DB that holds the policy (e.g.
                ``postgresql+psycopg://...`` or ``sqlite:///roles.db``). Use your
                own database. If omitted, the store is in-memory (not persisted) —
                fine for tests, not for production.
            roles_claim: JWT claim carrying a caller's roles (the external-IdP
                case). When absent, roles come from this store's own assignments
                (the no-IdP case). Both are served by the same store.
        """
        try:
            import casbin  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "ManagedRoleStore needs the optional casbin extra. "
                'Install it with: pip install "agno[casbin]"'
            ) from e

        import casbin

        model = casbin.Model()
        model.load_model_from_text(_MODEL_TEXT)
        if db_url:
            from casbin_sqlalchemy_adapter import Adapter

            self._enforcer = casbin.Enforcer(model, Adapter(db_url))
        else:
            self._enforcer = casbin.Enforcer(model)
        self._enforcer.enable_auto_save(True)  # mutations persist immediately
        self._roles_claim = roles_claim

    # ------------------------------------------------------------------ roles
    def set_role_scopes(self, role: str, scopes: List[str]) -> None:
        """Define (or replace) what a role can do, in agno scope terms."""
        self._enforcer.remove_filtered_policy(0, role)
        for scope in scopes:
            obj, act = scope_to_obj_act(scope)
            self._enforcer.add_policy(role, obj, act)

    def get_role_scopes(self, role: str) -> List[str]:
        """Return a role's scopes in agno terms (best-effort read-back)."""
        return sorted(
            _obj_act_to_scope(p[1], p[2]) for p in self._enforcer.get_filtered_policy(0, role) if len(p) >= 3
        )

    def remove_role(self, role: str) -> None:
        self._enforcer.remove_filtered_policy(0, role)
        self._enforcer.remove_filtered_grouping_policy(1, role)

    def list_roles(self) -> List[str]:
        return sorted({p[0] for p in self._enforcer.get_policy()})

    # ------------------------------------------------------------- assignments
    def assign(self, subject: str, role: str) -> None:
        """Give a subject a role (runtime, persisted)."""
        self._enforcer.add_role_for_user(subject, role)

    def unassign(self, subject: str, role: str) -> None:
        self._enforcer.delete_role_for_user(subject, role)

    def roles_of(self, subject: str) -> List[str]:
        return list(self._enforcer.get_roles_for_user(subject))

    # ----------------------------------------------------------------- gating
    def can_manage(self, principal_id: Optional[str], claims: Optional[Dict[str, Any]] = None) -> bool:
        """True if the caller may administer roles (i.e. satisfies ``agent_os:admin``).

        Only full admins manage the role store. An admin can be defined two ways,
        both handled here:
          - by a role in this store (``enforce(sub, "*", "*")``), or
          - by a role carried on the token, when ``roles_claim`` is set.
        Note this is intentionally NOT the generic provider ``check`` (which
        defers non-resource decisions to route scope mappings and would let any
        authenticated caller through).
        """
        if self._roles_claim and claims:
            roles = claims.get(self._roles_claim)
            if isinstance(roles, list):
                if any(bool(self._enforcer.enforce(r, "*", "*")) for r in roles):
                    return True
        if principal_id:
            return bool(self._enforcer.enforce(principal_id, "*", "*"))
        return False

    # --------------------------------------------------------------- provider
    @property
    def provider(self):
        """The AuthorizationProvider to plug into AuthorizationConfig."""
        from agno.os.authz.casbin_provider import CasbinAuthorizationProvider

        return CasbinAuthorizationProvider(self._enforcer, roles_claim=self._roles_claim)
