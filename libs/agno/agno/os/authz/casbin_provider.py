"""Optional Casbin-backed AuthorizationProvider.

An advanced, embedded authorization provider for customers who need more than
flat scopes: role hierarchies, ABAC conditions, and policy persisted/edited in
their own DB. Casbin is a pure-Python library (no external service) and its DB
adapter points at the customer's existing database, so this stays fully in the
customer's infra.

This is OPT-IN. Casbin is not a hard dependency of agno; install it with
``pip install agno[casbin]`` (or ``pip install casbin``). The import is lazy so
agno works without it. The default provider remains the zero-dependency
:class:`~agno.os.authz.scope_provider.ScopeAuthorizationProvider`.

Usage::

    import casbin
    from agno.os.authz.casbin_provider import CasbinAuthorizationProvider
    from agno.os.config import AuthorizationConfig

    enforcer = casbin.Enforcer("model.conf", adapter)   # adapter -> your DB
    agent_os = AgentOS(
        agents=[...],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[PUBLIC_KEY],
            authorization_provider=CasbinAuthorizationProvider(enforcer),
        ),
    )

Policy convention this provider assumes (Casbin ``p = sub, obj, act``):
- ``sub`` is the principal (the JWT ``sub`` / ``principal_id``)
- ``obj`` is ``"<resource_type>/<resource_id>"`` (e.g. ``agents/research-agent``),
  or ``"<resource_type>"`` for collection-level checks. Use ``keyMatch2`` in the
  model for wildcards like ``agents/*``.
- ``act`` is the action (``read`` / ``run`` / ...).
Role assignment uses Casbin grouping (``g, user, role``).
"""

from typing import Any, List, Optional, Set, Tuple

from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider


def scope_to_obj_act(scope: str) -> Tuple[str, str]:
    """Map an agno scope string to this provider's Casbin ``(obj, act)`` convention.

    Single source of truth shared with :class:`ManagedRoleStore` so the policy a
    role is *written* with and the request it is *checked* against use the same
    spelling.

    - ``agent_os:admin``             -> ("*", "*")
    - ``sessions:write``             -> ("sessions/*", "write")   (collection/global)
    - ``agents:research-agent:run``  -> ("agents/research-agent", "run")
    - ``agents:*:run``               -> ("agents/*", "run")
    """
    if scope == "agent_os:admin":
        return ("*", "*")
    parts = scope.split(":")
    if len(parts) == 2:
        return (f"{parts[0]}/*", parts[1])
    if len(parts) == 3:
        return (f"{parts[0]}/{parts[1]}", parts[2])
    raise ValueError(f"Unrecognised scope: {scope!r}")


class CasbinAuthorizationProvider(AuthorizationProvider):
    """Authorization decisions delegated to a Casbin enforcer."""

    def __init__(self, enforcer: Any, roles_claim: Optional[str] = None):
        """
        Args:
            enforcer: a configured ``casbin.Enforcer`` (sync). The caller owns
                the model + adapter (file, string, or a DB adapter pointed at
                their own database), so policy storage stays in their infra.
            roles_claim: optional JWT claim name carrying the caller's roles
                (e.g. ``"roles"`` for an Auth0/WorkOS token). When set and the
                claim is present, the caller's roles come FROM the token and we
                authorize each against the policy (handles "users with an IdP").
                When None or absent, roles come from Casbin's own ``g``
                assignments keyed on the subject (handles "users without an
                IdP"). Both populations are served by the same provider.
        """
        # Lazy validation: don't import casbin at module load, but fail clearly
        # if someone passes something that isn't an enforcer.
        if not hasattr(enforcer, "enforce"):
            raise TypeError(
                "CasbinAuthorizationProvider requires a casbin.Enforcer "
                "(install with `pip install agno[casbin]`). Got: "
                f"{type(enforcer)!r}"
            )
        self._enforcer = enforcer
        self._roles_claim = roles_claim

    def _obj(self, ctx: AuthorizationContext) -> Optional[str]:
        if not ctx.resource_type:
            return None
        return f"{ctx.resource_type}/{ctx.resource_id}" if ctx.resource_id else ctx.resource_type

    def _enforce(self, ctx: AuthorizationContext, obj: str, act: str) -> bool:
        """Run one Casbin decision for ``(obj, act)`` against ``ctx``'s identity.

        Roles-from-token (IdP case): if the token carries roles, authorize each
        role against the policy (a role matches its own policies in Casbin's
        RBAC), so we don't need stored ``g`` assignments for this user.
        Roles-from-store (no-IdP case): authorize the subject; Casbin resolves
        the subject's roles from its own ``g`` assignments.
        """
        if self._roles_claim:
            roles = ctx.claims.get(self._roles_claim)
            if isinstance(roles, list) and roles:
                return any(bool(self._enforcer.enforce(role, obj, act)) for role in roles)
        if not ctx.principal_id:
            return False
        return bool(self._enforcer.enforce(ctx.principal_id, obj, act))

    def check(self, ctx: AuthorizationContext) -> bool:
        # Non-resource checks can't be expressed as (sub,obj,act); defer (allow)
        # and let the route gate (authorize_route) handle them via the route's
        # required scopes.
        obj = self._obj(ctx)
        if obj is None or not ctx.action:
            return True
        return self._enforce(ctx, obj, ctx.action)

    def authorize_route(self, ctx: AuthorizationContext, required_scopes: List[str]) -> bool:
        """Route-level gate run by the middleware before the handler.

        For resource-typed routes (agents/teams/workflows) the middleware has
        already extracted ``(resource_type, resource_id, action)``, so decide on
        that via :meth:`check`. For every other route (sessions, memory, config,
        knowledge, ...) the middleware can't tag a resource type — so we evaluate
        the route's ``required_scopes`` directly against the policy. Without this,
        those routes would be ungated under this provider (any authenticated
        caller would pass), unlike the default scope provider which enforces them.
        Allow if ANY required scope is satisfied (``agent_os:admin`` satisfies all).
        """
        if ctx.resource_type:
            return self.check(ctx)
        if not required_scopes:
            return True
        for scope in required_scopes:
            try:
                obj, act = scope_to_obj_act(scope)
            except ValueError:
                continue
            if self._enforce(ctx, obj, act):
                return True
        return False

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> Set[str]:
        """Best-effort list-filtering support, derived from the principal's
        implicit permissions (direct + via roles). Returns ``{"*"}`` for
        wildcard/collection grants, otherwise the set of specific ids.
        """
        if not ctx.resource_type or not ctx.principal_id:
            return set()

        rt = ctx.resource_type
        action = ctx.action
        try:
            perms = self._enforcer.get_implicit_permissions_for_user(ctx.principal_id)
        except Exception:
            # Some models/adapters don't support implicit perms; fall back to
            # explicit policy for the user.
            perms = [p for p in self._enforcer.get_policy() if p and p[0] == ctx.principal_id]

        ids: Set[str] = set()
        for perm in perms:
            # perm is [sub, obj, act, ...]
            p_obj = perm[1] if len(perm) > 1 else None
            p_act = perm[2] if len(perm) > 2 else None
            if p_obj is None:
                continue
            if action and p_act not in (None, action, "*"):
                continue
            if p_obj in ("*", f"{rt}/*", rt):
                return {"*"}
            prefix = f"{rt}/"
            if p_obj.startswith(prefix):
                ids.add(p_obj[len(prefix):])
        return ids
