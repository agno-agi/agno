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
    """Allow if ANY of the wrapped providers allows (union of grants).

    INVARIANT: every provider in the list is a GRANT source. Because the
    composition is an OR, a provider can only ever *widen* access — it can never
    restrict what another provider grants. Do NOT add a provider whose purpose is
    to deny (an IP fence, a compliance/step-up gate); under OR its "deny" is
    silently overridden by any other provider's "allow". Such a control belongs
    upstream (middleware) or inside a single provider's own logic, not as a peer
    in this list.
    """

    def __init__(self, providers: List[AuthorizationProvider]):
        if not providers:
            raise ValueError("CompositeAuthorizationProvider needs at least one provider")
        self.providers = list(providers)

    def check(self, ctx: AuthorizationContext) -> bool:
        # A non-resource check (no resource_type/action) isn't expressible as a
        # per-resource decision; by contract every provider DEFERS it to the route
        # gate (authorize_route). Encode that deferral uniformly here rather than
        # OR-ing the providers' vacuous "True"s — otherwise a provider that DID
        # mean to deny a non-resource check would be silently overridden.
        if not ctx.resource_type or not ctx.action:
            return True
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
