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

from typing import Any, List, Set

from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider
from agno.utils.log import log_warning


def _abstained(provider: AuthorizationProvider, e: Exception) -> None:
    """Log that one plane errored and is being treated as ABSTAIN.

    The composition is an OR of grant sources, so a plane that errors (e.g. an
    OpenFGA backend that's unreachable) must not fail the whole request — that would
    turn one plane's outage into a 500 even when a healthy peer plane would grant.
    Each call site treats the error as "this plane grants nothing" and defers to the
    other planes; if every plane errors the OR collapses to deny (fail-closed). The
    error is logged so the outage is visible rather than silent.
    """
    log_warning(f"Authorization plane {type(provider).__name__} errored; treating as abstain: {e}")


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
        # A composite is a scope plane iff ANY plane it wraps is one. Computed from the
        # children (which set it recursively) so a nested composite resolves correctly --
        # token_scopes_are_authoritative reads this flag rather than walking one level.
        self.enforces_token_scopes = any(getattr(p, "enforces_token_scopes", False) for p in self.providers)

    def check(self, ctx: AuthorizationContext) -> bool:
        # A non-resource check (no resource_type/action) isn't expressible as a
        # per-resource decision; by contract every provider DEFERS it to the route
        # gate (authorize_route). Encode that deferral uniformly here rather than
        # OR-ing the providers' vacuous "True"s — otherwise a provider that DID
        # mean to deny a non-resource check would be silently overridden.
        if not ctx.resource_type or not ctx.action:
            return True
        for provider in self.providers:
            try:
                if provider.check(ctx):
                    return True
            except Exception as e:
                _abstained(provider, e)
        return False

    def authorize_route(self, ctx: AuthorizationContext, required_scopes: List[str]) -> bool:
        for provider in self.providers:
            try:
                if provider.authorize_route(ctx, required_scopes):
                    return True
            except Exception as e:
                _abstained(provider, e)
        return False

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> Set[str]:
        ids: Set[str] = set()
        for provider in self.providers:
            try:
                got = provider.accessible_resource_ids(ctx)
            except Exception as e:
                _abstained(provider, e)
                continue
            if "*" in got:
                return {"*"}
            ids |= got
        return ids

    def filter_accessible(self, ctx: AuthorizationContext, resources: List[Any]) -> List[Any]:
        # Union of grants (OR): a resource is visible if ANY plane's deny-aware
        # filter keeps it. This is why a deny belongs INSIDE a single provider (so it
        # carves that provider's grant) and never as a peer plane — under the union a
        # peer's allow still wins, exactly as the INVARIANT above requires.
        keep: Set[Any] = set()
        for provider in self.providers:
            try:
                kept = provider.filter_accessible(ctx, resources)
            except Exception as e:
                _abstained(provider, e)
                continue
            for resource in kept:
                keep.add(getattr(resource, "id", None))
        return [r for r in resources if getattr(r, "id", None) in keep]
