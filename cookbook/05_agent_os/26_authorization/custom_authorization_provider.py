"""
Custom AuthorizationProvider - the minimal "bring your own decision engine" path.

(New to authorization? Read managed_roles.py first. For a production-shaped custom
provider that integrates a login service like WorkOS/Auth0, see idp_workos_auth0.py.)

The scope tier (default) and the managed-roles tier both think in agno SCOPES. If
your access model isn't scopes - it's ReBAC ("is this user an owner of this
resource?"), ABAC ("same tenant?"), or a call out to your own policy engine - you
write an AuthorizationProvider and plug it in. That ONE object is the whole
integration; the rest of AgentOS (the request pipeline, the two enforcement points)
stays the same.

An AuthorizationProvider answers two questions (the ABC's two abstract methods):

  - check(ctx)                  -> "may THIS caller do THIS action on THIS resource?"
  - accessible_resource_ids(ctx)-> for list endpoints: which ids may they see?
                                   ({"*"} means "all of them".)

Two more methods you can override:

  - authorize_route(ctx, required_scopes)  the route-level gate the JWT middleware
                                   runs BEFORE the request reaches a handler. It
                                   governs EVERY mapped route, including the ones with
                                   no resource_type (/sessions, /config, /metrics,
                                   /databases/all/migrate, ...). The ABC default fails
                                   those closed (it cannot express a non-resource
                                   question), so a provider that means to authorize
                                   them MUST override this -- see below.
  - require / filter_accessible    built on check / accessible_resource_ids.

The example below uses a deliberately tiny, NON-scope decision model to make the
seam obvious: the token carries a `tier` claim, and a small Python dict says what
each tier may do. Swap the body of check()/accessible_resource_ids() for a call to
your own engine and nothing else changes.

Run it:
    pip install agno
    python custom_authorization_provider.py
(no extra services, no database needed - we only check who is allowed.)
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Set

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider
from agno.os.config import AuthorizationConfig

JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "custom-provider-os"

os.makedirs("tmp", exist_ok=True)


# ---------------------------------------------------------------------------
# The whole integration: implement the AuthorizationProvider ABC.
# ---------------------------------------------------------------------------

# Our (toy) access model: a "tier" on the token decides what actions are allowed.
# This is NOT scopes - it's whatever model you like. Replace with your own engine.
TIER_ACTIONS = {
    "reader": {"read"},  # may read any resource
    "runner": {"read", "run"},  # may read + run any resource
    "owner": {"read", "run", "write"},  # may do anything
}


class TierAuthorizationProvider(AuthorizationProvider):
    """Decide access from a custom `tier` claim on the token.

    agno hands every decision an AuthorizationContext describing the caller and
    what they're trying to do. We read our `tier` claim off ctx.claims and answer
    from a plain dict. The fields we use here:
      ctx.claims        the full decoded JWT payload (where our `tier` lives)
      ctx.resource_type "agents" / "teams" / "workflows" / ... (None = non-resource)
      ctx.action        "read" / "run" / "write" / ... (None = non-resource)
    (ctx also exposes principal_id, scopes, resource_id, admin_scope for richer
    models - we just don't need them here.)
    """

    def _allowed_actions(self, ctx: AuthorizationContext) -> Set[str]:
        tier = ctx.claims.get("tier")
        return TIER_ACTIONS.get(tier, set())

    def check(self, ctx: AuthorizationContext) -> bool:
        # A non-resource check (no resource_type/action) is DEFERRED, not denied:
        # the route-level gate (authorize_route) governs those paths. Returning
        # False here would wrongly block non-resource routes. This mirrors the
        # framework's native engine convention.
        if not ctx.resource_type or not ctx.action:
            return True
        return ctx.action in self._allowed_actions(ctx)

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> Set[str]:
        # For list endpoints (GET /agents, ...): which ids may they see? Here a
        # tier either may read everything or nothing, so it's "*" (all) or empty.
        # A ReBAC model would instead return the specific ids this user owns.
        if "read" in self._allowed_actions(ctx):
            return {"*"}
        return set()

    def authorize_route(self, ctx: AuthorizationContext, required_scopes: list) -> bool:
        # The route gate covers BOTH resource routes AND non-resource routes
        # (/sessions, /config, /metrics, /databases/all/migrate, ...). Our tier model
        # is resource-agnostic, so we decide from the actions the route requires --
        # the trailing segment of each required scope ("sessions:read" -> "read").
        # This is what keeps non-resource routes gated: the ABC default fails them
        # closed precisely so a provider cannot leave them open by accident. A route
        # with no required scopes is public.
        if not required_scopes:
            return True
        allowed = self._allowed_actions(ctx)
        return all(scope.rsplit(":", 1)[-1] in allowed for scope in required_scopes)

    # require() / filter_accessible() use the ABC defaults, built on check() /
    # accessible_resource_ids() above.


# ---------------------------------------------------------------------------
# Wire it in: AuthorizationConfig(authorization_provider=<your provider>).
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/agentos.db")
research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS with a custom authorization provider",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        # The seam: hand AgentOS your provider. That's the entire integration.
        authorization_provider=TierAuthorizationProvider(),
    ),
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

    def token(sub: str, tier: str) -> str:
        return jwt.encode(
            {
                "sub": sub,
                "aud": OS_ID,
                "tier": tier,  # our custom claim - the provider reads this
                "exp": datetime.now(UTC) + timedelta(hours=24),
            },
            JWT_SECRET,
            algorithm="HS256",
        )

    def show(label: str, tok: str, method: str, path: str, note: str = "") -> None:
        r = client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {tok}"},
            data={"message": "hi"},
        )
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:48s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 80)
    print("CUSTOM PROVIDER - a `tier` claim decides what you can do")
    print("=" * 80)
    print("  tiers:  reader = read | runner = read + run | owner = anything")
    print("  each caller makes a real request. ALLOWED = got in, BLOCKED = bounced.\n")

    show(
        "reader  LOOK at the agent",
        token("r", "reader"),
        "GET",
        "/agents/research-agent",
        "readers can read",
    )
    show(
        "reader  RUN the agent",
        token("r", "reader"),
        "POST",
        "/agents/research-agent/runs",
        "readers can't run -> bounced",
    )
    show(
        "runner  RUN the agent",
        token("n", "runner"),
        "POST",
        "/agents/research-agent/runs",
        "runners can run",
    )
    show(
        "owner   RUN the agent",
        token("o", "owner"),
        "POST",
        "/agents/research-agent/runs",
        "owners can do anything",
    )
    show(
        "guest   LOOK at the agent",
        token("g", "guest"),
        "GET",
        "/agents/research-agent",
        "unknown tier -> bounced",
    )

    print("=" * 80)
    print(
        "the point: one AuthorizationProvider IS the whole integration. Swap the body"
    )
    print(
        "of check()/accessible_resource_ids() for your own engine; nothing else changes."
    )
    print("=" * 80)
