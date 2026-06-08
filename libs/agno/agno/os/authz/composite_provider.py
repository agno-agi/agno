"""Run two authorization planes on one AgentOS, in parallel.

Real deployments often have two populations hitting the same OS:

- **Operators** — admins managing the OS through the agno-os frontend. agno's
  control plane mints them a token that already carries scopes, so they're
  authorized straight from the token (a :class:`ScopeAuthorizationProvider`).
- **End users** — the customer's own users, whose access is managed at runtime in
  the OS-local :class:`~agno.os.authz.role_store.ManagedRoleStore`. Their token
  carries identity; the store decides.

A single provider can't be both "trust the token's scopes" and "ignore the token,
ask the store." :class:`CompositeAuthorizationProvider` composes them: a request
is allowed if **any** wrapped provider allows it. So both planes enforce on the
same OS at the same time:

    from agno.os.authz.composite_provider import CompositeAuthorizationProvider
    from agno.os.authz.scope_provider import ScopeAuthorizationProvider

    provider = CompositeAuthorizationProvider([
        ScopeAuthorizationProvider(),   # operators: scopes from the token
        roles.provider,                 # end users: the OS-local managed store
    ])
    AuthorizationConfig(authorization_provider=provider, ...)

Order doesn't affect the allow/deny outcome (it's an OR), only the order providers
are consulted. ``accessible_resource_ids`` returns the union (``{"*"}`` wins).
"""

from typing import List, Set

from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider


class CompositeAuthorizationProvider(AuthorizationProvider):
    """Allow if ANY of the wrapped providers allows (union of grants)."""

    def __init__(self, providers: List[AuthorizationProvider]):
        if not providers:
            raise ValueError("CompositeAuthorizationProvider needs at least one provider")
        self.providers = list(providers)

    def check(self, ctx: AuthorizationContext) -> bool:
        return any(p.check(ctx) for p in self.providers)

    def authorize_route(self, ctx: AuthorizationContext, required_scopes: List[str]) -> bool:
        return any(p.authorize_route(ctx, required_scopes) for p in self.providers)

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> Set[str]:
        ids: Set[str] = set()
        for p in self.providers:
            got = p.accessible_resource_ids(ctx)
            if "*" in got:
                return {"*"}
            ids |= got
        return ids
