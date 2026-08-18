"""
Custom authorization provider for AgentOS (bring your own decision model).

When your access model isn't scopes — ReBAC ("is this user an owner?"), ABAC
("same tenant?"), or a role/permission scheme that lives in your own system — you
implement the `AuthorizationProvider` interface and AgentOS calls it on every
request. You keep the whole request pipeline and both enforcement points; you only
own the decision.

This example keys off a single `tier` claim on the token (reader / runner / owner)
instead of scopes, to show the seam clearly. Swap the body of `check()` for your
real logic (a DB lookup, an OpenFGA call, a tenant comparison, ...).

Run this file; it prints a token per tier. Call the API with one to see it
enforced:

    curl http://localhost:7777/agents/research-agent -H "Authorization: Bearer <reader-token>"
    curl -X POST http://localhost:7777/agents/research-agent/runs \
         -H "Authorization: Bearer <reader-token>" -F "message=hi"   # -> 403
"""

from datetime import UTC, datetime, timedelta
from typing import Set

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider
from agno.os.config import AuthorizationConfig

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT secret (use an environment variable in production).
JWT_SECRET = "a-string-secret-at-least-256-bits-long"

# What each tier may do. "read" is viewing; "run" is executing an agent/team/etc.
TIER_ACTIONS = {
    "reader": {"read"},
    "runner": {"read", "run"},
    "owner": {"read", "run", "write", "delete"},
}


class TierAuthorizationProvider(AuthorizationProvider):
    """Decides access from a `tier` claim on the token instead of scopes."""

    def _tier(self, ctx: AuthorizationContext) -> str:
        # ctx.claims is the full decoded JWT; read whatever your model needs.
        return str(ctx.claims.get("tier", ""))

    def check(self, ctx: AuthorizationContext) -> bool:
        """May this caller do ctx.action on ctx.resource_type/ctx.resource_id?"""
        # Non-resource checks (no resource_type/action) are decided at the route
        # gate; defer them here so we don't wrongly deny them.
        if not ctx.resource_type or not ctx.action:
            return True
        return ctx.action in TIER_ACTIONS.get(self._tier(ctx), set())

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> Set[str]:
        """Which ids of ctx.resource_type the caller may access, for list views.
        `{"*"}` means all of them; an empty set means none."""
        if ctx.action and ctx.action in TIER_ACTIONS.get(self._tier(ctx), set()):
            return {"*"}
        return set()

    # authorize_route(), require() and filter_accessible() inherit sensible
    # defaults from AuthorizationProvider (they build on check()), so a custom
    # provider only has to implement the two methods above.


# Setup the database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
)

agent_os = AgentOS(
    description="AgentOS protected by a custom authorization provider",
    agents=[research_agent],
    db=db,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        authorization_provider=TierAuthorizationProvider(),
    ),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------


def make_token(sub: str, tier: str) -> str:
    """Mint a signed JWT carrying the caller's tier (the provider reads it)."""
    payload = {
        "sub": sub,
        "tier": tier,
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


if __name__ == "__main__":
    """
    Run AgentOS with a custom authorization provider.

    The provider decides from each token's `tier` claim:
      reader — read works, run is 403
      runner — read and run work
      owner  — everything

    Test:
      curl http://localhost:7777/agents/research-agent -H "Authorization: Bearer <token>"
      curl -X POST http://localhost:7777/agents/research-agent/runs \
           -H "Authorization: Bearer <token>" -F "message=hi"
    """
    print("dana  (reader):", make_token("dana", "reader"))
    print("raj   (runner):", make_token("raj", "runner"))
    print("olga  (owner) :", make_token("olga", "owner"))
    agent_os.serve(app="custom_authorization_provider:app", port=7777, reload=True)
