"""Run two authorization planes on one AgentOS, in parallel.

Real deployments often have two populations hitting the same OS:

- **Operators** — admins managing the OS through the agno-os frontend. agno's
  control plane mints them a token that already carries scopes, so they're
  authorized straight from the token (a :class:`ScopeAuthorizationProvider`).
- **End users** — the customer's own users, whose access is managed at runtime in
  the OS-local :class:`~agno.os.authz.role_store.ManagedRoleStore`. Their token
  carries identity; the store decides.

A single provider can't be both "trust the token's scopes" and "ignore the token,
ask the store." The public way to run several planes is to pass a **list** of
providers to ``AuthorizationConfig`` / ``AgentOS`` — a request is allowed if any
of them allows it::

    AuthorizationConfig(authorization_provider=[
        ScopeAuthorizationProvider(),   # operators: scopes from the token
        roles.provider,                 # end users: the OS-local managed store
    ])

AgentOS composes that list with the internal class below. It's an OR, so order
only affects which provider is consulted first, not the outcome;
``accessible_resource_ids`` returns the union (``{"*"}`` wins). This class is an
implementation detail — prefer the list form above.
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
