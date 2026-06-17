"""The pluggable policy engine behind managed roles — the swappable backend seam.

:class:`~agno.os.authz.role_store.ManagedRoleStore` is the agno-native product
surface (create roles, set scopes, assign, audit). The *engine* underneath —
which actually stores policy and answers "is this allowed?" — is a swappable
adapter behind this narrow port. agno's own
:class:`~agno.os.authz.native_engine.NativePolicyEngine` is the default (zero
third-party dependencies); swapping to another backend (OpenFGA, SpiceDB, ...)
means implementing :class:`PolicyEngine` and passing it as
``ManagedRoleStore(engine=...)`` — no change to the store's API, the ``/authz``
router, the cookbooks, or anything SDK users see.

The port speaks only agno terms — roles, subjects, scope strings, allow/deny.
No engine types (obj/act tuples, OpenFGA tuples) leak across it.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set, Tuple

from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider

# A scope with its effect, e.g. ("agents:*:read", "allow") / ("agents:x:run", "deny").
ScopeEntry = Tuple[str, str]


def normalize_roles_claim(claims: Optional[Dict[str, Any]], roles_claim: Optional[str]) -> Optional[List[str]]:
    """A caller's roles from a JWT claim, or None when absent/unusable. Accepts a
    single string (e.g. WorkOS sends one ``role``) or a list. One owner for this
    coercion so the gate (``EngineAuthorizationProvider``) and the admin check
    (``ManagedRoleStore.can_manage``) can't drift — both are security-relevant."""
    if not roles_claim or not claims:
        return None
    raw = claims.get(roles_claim)
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, list) and raw:
        return raw
    return None


class PolicyEngine(ABC):
    """The backend that stores managed-role policy and answers access questions.

    Implement these ~dozen methods (all in agno terms) to back managed roles with
    a different engine. Identity for decisions is given two ways, mirroring the two
    populations: ``subject`` (the engine resolves its roles from stored
    assignments — the no-IdP case) and ``roles`` (roles carried on the token — the
    IdP case). When ``roles`` is provided it takes precedence; otherwise the
    ``subject``'s stored assignments decide.
    """

    # --- authoring: roles -> scopes ---
    @abstractmethod
    def set_role_scopes(self, role: str, entries: List[ScopeEntry]) -> None:
        """Replace a role's entire scope set with ``entries`` (scope, effect)."""

    @abstractmethod
    def add_scope(self, role: str, scope: str, effect: str = "allow") -> None:
        """Add (or flip the effect of) a single scope on a role."""

    @abstractmethod
    def remove_scope(self, role: str, scope: str) -> None:
        """Remove a single scope from a role (no-op if absent)."""

    @abstractmethod
    def get_role_scopes(self, role: str) -> List[ScopeEntry]:
        """A role's scopes as (scope, effect) entries."""

    @abstractmethod
    def remove_role(self, role: str) -> None:
        """Delete a role: its scopes and any assignments to it."""

    @abstractmethod
    def list_roles(self) -> List[str]:
        """All role names known to the engine."""

    # --- assignments: subject -> roles ---
    @abstractmethod
    def assign(self, subject: str, role: str) -> None: ...

    @abstractmethod
    def unassign(self, subject: str, role: str) -> None: ...

    @abstractmethod
    def roles_of(self, subject: str) -> List[str]: ...

    # --- decisions ---
    @abstractmethod
    def check_resource(
        self,
        resource_type: Optional[str],
        resource_id: Optional[str],
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> bool:
        """May the identity perform ``action`` on this resource (or collection)?"""

    @abstractmethod
    def check_scope(self, scope: str, *, subject: Optional[str] = None, roles: Optional[List[str]] = None) -> bool:
        """Does the identity satisfy a required ``scope`` string? (Unmappable
        scope -> False.)"""

    @abstractmethod
    def accessible_resource_ids(
        self,
        resource_type: str,
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Set[str]:
        """Resource ids of ``resource_type`` the identity may access for ``action``
        (``{"*"}`` = all)."""

    def denied_resource_ids(
        self,
        resource_type: str,
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Set[str]:
        """Concrete resource ids of ``resource_type`` the identity is explicitly
        DENIED for ``action`` (deny-overrides). Used to carve denials out of the
        list-visibility set so a wildcard allow + per-resource deny doesn't leak the
        denied resource into list endpoints. Default: no engine-level denies."""
        return set()


class EngineAuthorizationProvider(AuthorizationProvider):
    """An :class:`AuthorizationProvider` backed by any :class:`PolicyEngine`.

    Engine-agnostic: it resolves the caller's identity (subject + optional
    token-carried roles) from the request context and delegates every decision to
    the engine. This is what ``ManagedRoleStore.provider`` returns, regardless of
    which engine is plugged in.
    """

    def __init__(self, engine: PolicyEngine, roles_claim: Optional[str] = None):
        self._engine = engine
        self._roles_claim = roles_claim

    def _identity(self, ctx: AuthorizationContext) -> Tuple[Optional[str], Optional[List[str]]]:
        """(subject, roles) for the engine. ``roles`` is the token-carried list
        when a ``roles_claim`` is configured and present; otherwise None so the
        subject's stored assignments decide."""
        return ctx.principal_id, normalize_roles_claim(ctx.claims, self._roles_claim)

    def check(self, ctx: AuthorizationContext) -> bool:
        subject, roles = self._identity(ctx)
        return self._engine.check_resource(ctx.resource_type, ctx.resource_id, ctx.action, subject=subject, roles=roles)

    def authorize_route(self, ctx: AuthorizationContext, required_scopes: List[str]) -> bool:
        subject, roles = self._identity(ctx)
        # A resource route with a concrete single action: decide on the extracted
        # (type, id, action) — the per-resource gate.
        if ctx.resource_type and ctx.action:
            return self._engine.check_resource(
                ctx.resource_type, ctx.resource_id, ctx.action, subject=subject, roles=roles
            )
        # Otherwise — a non-resource route, or a resource route whose required scopes
        # span more than one action (ctx.action is None) — require ALL of the route's
        # scopes, matching the scope provider's AND semantics. Never fall through to a
        # blanket allow: a multi-action resource route used to hit check_resource with
        # action=None and be waved through. Evaluate each scope against the specific
        # resource when one is known, else as a generic scope string.
        if not required_scopes:
            return True
        for scope in required_scopes:
            if ctx.resource_type and ctx.resource_id:
                action = scope.rsplit(":", 1)[1] if ":" in scope else scope
                ok = self._engine.check_resource(
                    ctx.resource_type, ctx.resource_id, action, subject=subject, roles=roles
                )
            else:
                ok = self._engine.check_scope(scope, subject=subject, roles=roles)
            if not ok:
                return False
        return True

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> Set[str]:
        if not ctx.resource_type:
            return set()
        subject, roles = self._identity(ctx)
        return self._engine.accessible_resource_ids(ctx.resource_type, ctx.action, subject=subject, roles=roles)

    def filter_accessible(self, ctx: AuthorizationContext, resources: List[Any]) -> List[Any]:
        """Deny-aware list filtering: accessible ids MINUS explicitly-denied ids, so a
        wildcard allow with a per-resource deny (``agents:*:read`` + a deny on
        ``agents:secret``) excludes the denied resource — keeping list endpoints
        consistent with :meth:`check` / the per-resource gate (deny-overrides)."""
        if not ctx.resource_type:
            return resources
        subject, roles = self._identity(ctx)
        accessible = self._engine.accessible_resource_ids(ctx.resource_type, ctx.action, subject=subject, roles=roles)
        denied = self._engine.denied_resource_ids(ctx.resource_type, ctx.action, subject=subject, roles=roles)
        wildcard = "*" in accessible
        return [
            r
            for r in resources
            if getattr(r, "id", None) not in denied and (wildcard or getattr(r, "id", None) in accessible)
        ]
