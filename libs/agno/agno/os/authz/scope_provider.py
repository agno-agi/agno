"""Default authorization provider: JWT-scope RBAC.

This is the built-in implementation and preserves AgentOS's existing behaviour
exactly — it delegates to :func:`agno.os.scopes.has_required_scopes` and
:func:`agno.os.scopes.get_accessible_resource_ids`, the same functions the
request pipeline used before the provider seam existed. No external service, no
new dependency: it runs against the scopes already in the JWT.

Swapping to a different model (OpenFGA, Cerbos, a bespoke ReBAC engine)
means implementing :class:`agno.os.authz.provider.AuthorizationProvider`
instead of this class — the rest of the pipeline is unchanged.
"""

from typing import List, Set

from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider
from agno.os.scopes import get_accessible_resource_ids, has_required_scopes


class ScopeAuthorizationProvider(AuthorizationProvider):
    """RBAC via JWT scope strings (``resource:action``, ``resource:<id>:action``)."""

    def check(self, ctx: AuthorizationContext) -> bool:
        # A non-resource check (no resource_type) can't be expressed as a scope
        # here; treat it as allowed and let route-level scope mappings handle it.
        if not ctx.resource_type or not ctx.action:
            return True

        required = [f"{ctx.resource_type}:{ctx.action}"]
        return has_required_scopes(
            ctx.scopes,
            required,
            resource_type=ctx.resource_type,
            resource_id=ctx.resource_id,
            admin_scope=ctx.admin_scope,
        )

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> Set[str]:
        if not ctx.resource_type:
            return set()
        return get_accessible_resource_ids(
            ctx.scopes,
            ctx.resource_type,
            admin_scope=ctx.admin_scope,
            action=ctx.action,
        )

    def authorize_route(self, ctx: AuthorizationContext, required_scopes: List[str]) -> bool:
        """Original middleware route gate: does the token satisfy the scopes the
        route requires, in the context of the resource being accessed.
        """
        if not required_scopes:
            return True
        return has_required_scopes(
            ctx.scopes,
            required_scopes,
            resource_type=ctx.resource_type,
            resource_id=ctx.resource_id,
            admin_scope=ctx.admin_scope,
        )
