"""Authorization provider interface.

Defines the decision context handed to a provider and the abstract base every
provider implements. Keeping this dependency-free (only stdlib + typing) means
the interface can live in the OSS SDK while concrete providers — including ones
that call out to an external policy engine — are layered on top.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class AuthorizationContext:
    """Everything a provider needs to make an access decision.

    A provider is free to use as much or as little of this as its model
    requires. The built-in scope provider only looks at ``scopes`` /
    ``resource_type`` / ``resource_id`` / ``action`` / ``admin_scope``; a ReBAC
    or ABAC provider would additionally lean on ``principal_id`` and the full
    ``claims`` (tenant, groups, ownership hints, etc.).

    Attributes:
        principal_id: The authenticated subject (JWT ``sub``), or None when
            unauthenticated.
        scopes: Scope strings from the token's ``scopes`` claim.
        claims: The full decoded JWT payload, for providers that key off
            arbitrary claims (tenant_id, groups, ...).
        resource_type: Resource family being accessed ("agents", "teams",
            "workflows", ...), or None for non-resource checks.
        resource_id: Specific resource id, or None for list/collection checks.
        action: Action being attempted ("read", "run", "write", ...).
        admin_scope: The scope string that grants full bypass (default
            ``agent_os:admin``).

            IMPORTANT -- this is a *scope-plane* feature. It is honoured by
            :class:`~agno.os.authz.scope_provider.ScopeAuthorizationProvider`,
            which reads it off the caller's token scopes. Providers that do not
            authorize from token scopes deliberately ignore it and model admin in
            their own terms instead: the managed-role engine grants an admin ROLE
            (a role whose scopes include ``agent_os:admin``), and a relationship
            (ReBAC) provider expects an admin RELATIONSHIP. So a token carrying
            ``agent_os:admin`` is NOT automatically an admin under a role or ReBAC
            provider used on its own -- if you want token-scope admins alongside
            one of those, run the scope provider as a second plane
            (``authorization_provider=[ScopeAuthorizationProvider(), other]``),
            where the OR composition gives you the bypass.
    """

    principal_id: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    claims: Dict[str, Any] = field(default_factory=dict)
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    action: Optional[str] = None
    admin_scope: Optional[str] = None


class AuthorizationProvider(ABC):
    """Strategy for answering AgentOS authorization questions.

    Two primitives every provider must answer:

    - :meth:`check` — boolean "may this context do this action on this
      resource?"
    - :meth:`accessible_resource_ids` — for list endpoints, which resource ids
      of a type the principal may access (``{"*"}`` means all).

    :meth:`require` and :meth:`filter_accessible` have sensible default
    implementations on top of those two; override them only if the provider can
    do something smarter (e.g. a single batch call to an external engine).
    """

    @abstractmethod
    def check(self, ctx: AuthorizationContext) -> bool:
        """Return True if the action in ``ctx`` is allowed."""
        ...

    @abstractmethod
    def accessible_resource_ids(self, ctx: AuthorizationContext) -> Set[str]:
        """Return the set of resource ids of ``ctx.resource_type`` the
        principal may access for ``ctx.action``. ``{"*"}`` denotes wildcard
        (all) access.
        """
        ...

    def authorize_route(self, ctx: AuthorizationContext, required_scopes: List[str]) -> bool:
        """Route-level gate run by the JWT middleware before the request reaches
        the endpoint.

        ``required_scopes`` is the scope vocabulary the default route→scope
        mapping produced for this path (e.g. ``["agents:run"]``). A scope-based
        provider uses it directly; a provider with a different model (ReBAC/ABAC)
        ignores it and decides from :meth:`check` instead.

        Default implementation gives a custom provider full control of the
        per-resource gate through :meth:`check`, without having to understand scope
        strings. :class:`~agno.os.authz.scope_provider.ScopeAuthorizationProvider`
        overrides this to preserve the original scope-matching behaviour.

        SECURITY -- fail closed on non-resource routes. Only ``/agents``, ``/teams``,
        ``/workflows`` and ``/a2a`` carry a ``resource_type``; every other mapped
        route (``/sessions``, ``/memories``, ``/config``, ``/databases/all/migrate``,
        ``/service-accounts``, ...) reaches here with ``resource_type``/``action``
        unset. By contract :meth:`check` DEFERS such a context (returns ``True``,
        leaving it to the route gate), so deferring to it here would ALLOW every
        non-resource route for any authenticated caller -- a full authorization
        bypass for a provider that only implements :meth:`check`. Such routes are not
        expressible as a per-resource question, so a provider that means to authorize
        them MUST override this method (deciding from ``required_scopes`` or its own
        model). A route with no required scopes is public and still allowed.
        """
        if not required_scopes:
            return True
        if not ctx.resource_type or not ctx.action:
            return False
        return self.check(ctx)

    def require(self, ctx: AuthorizationContext) -> None:
        """Raise ``PermissionError`` if :meth:`check` denies ``ctx``.

        The HTTP layer translates this into a 403; keeping the provider raising
        a plain ``PermissionError`` avoids coupling it to FastAPI.
        """
        if not self.check(ctx):
            raise PermissionError(
                f"Access denied to {ctx.action} {ctx.resource_type}"
                + (f"/{ctx.resource_id}" if ctx.resource_id else "")
            )

    def filter_accessible(self, ctx: AuthorizationContext, resources: List[Any]) -> List[Any]:
        """Filter ``resources`` (objects with an ``id``) to those the principal
        may access, using :meth:`accessible_resource_ids`.

        Default implementation does one ``accessible_resource_ids`` call and
        filters in-process. Providers backed by an external engine may override
        with a batched authorization query.
        """
        accessible = self.accessible_resource_ids(ctx)
        if "*" in accessible:
            return resources
        return [r for r in resources if getattr(r, "id", None) in accessible]
