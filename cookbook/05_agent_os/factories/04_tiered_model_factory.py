"""Tiered Model Factory -- model selection based on subscription tier.

Demonstrates per-tenant model selection: enterprise tenants get the best model,
free-tier users get a cheaper one. The tier comes from JWT claims (trusted),
so clients can't self-upgrade by changing a request field.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/factories/04_tiered_model_factory.py

Test:
    # Free tier (cheaper model)
    curl -X POST http://localhost:7777/v1/agents/tiered-agent/runs \
        -H "Authorization: Bearer <FREE_TOKEN>" \
        -F 'message=Explain quantum computing in one sentence' \
        -F 'stream=false'

    # Enterprise tier (best model)
    curl -X POST http://localhost:7777/v1/agents/tiered-agent/runs \
        -H "Authorization: Bearer <ENTERPRISE_TOKEN>" \
        -F 'message=Explain quantum computing in one sentence' \
        -F 'stream=false'
"""

from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from agno.agent import Agent, AgentFactory
from agno.agent.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JWT_SECRET = "a-string-secret-at-least-256-bits-long"

TIER_MODELS = {
    "free": "gpt-4.1-mini",
    "pro": "gpt-4.1",
    "enterprise": "gpt-5.4",
}

TIER_INSTRUCTIONS = {
    "free": "You are a helpful assistant. Keep responses brief (2-3 sentences max).",
    "pro": "You are a helpful assistant. Provide detailed, well-structured responses.",
    "enterprise": (
        "You are a premium assistant. Provide comprehensive, expert-level responses. "
        "Use examples, cite reasoning, and anticipate follow-up questions."
    ),
}


# ---------------------------------------------------------------------------
# JWT middleware (same pattern as 03_jwt_role_factory.py)
# ---------------------------------------------------------------------------


class TierJWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
                request.state.claims = payload
                request.state.user_id = payload.get("sub")
            except pyjwt.PyJWTError:
                pass
        return await call_next(request)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_tiered_agent(ctx: RequestContext) -> Agent:
    """Build an agent with model quality based on the caller's subscription tier."""
    claims = ctx.trusted.claims
    tier = claims.get("tier", "free")
    org_id = claims.get("org_id", "unknown")
    user_id = ctx.user_id or "anonymous"

    # Fall back to free tier for unknown values
    model_id = TIER_MODELS.get(tier, TIER_MODELS["free"])
    instructions = TIER_INSTRUCTIONS.get(tier, TIER_INSTRUCTIONS["free"])

    return Agent(
        id=f"tiered_{org_id}_{user_id}",
        model=OpenAIResponses(id=model_id),
        instructions=instructions,
        add_datetime_to_context=True,
        markdown=True,
    )


tiered_factory = AgentFactory(
    id="tiered-agent",
    name="Tiered Assistant",
    description="Model quality scales with subscription tier (free/pro/enterprise)",
    factory=build_tiered_agent,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="factory-tiered-demo",
    description="Demo: subscription-tier-based model selection",
    agents=[tiered_factory],
)
app = agent_os.get_app()
app.add_middleware(TierJWTMiddleware)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    def make_token(tier: str, org_id: str = "acme", user_id: str = "user_1") -> str:
        payload = {
            "sub": user_id,
            "tier": tier,
            "org_id": org_id,
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iat": datetime.now(UTC),
        }
        return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

    print("Test tokens (valid for 24h):")
    print()
    print(f"  FREE:        {make_token('free')}")
    print(f"  PRO:         {make_token('pro')}")
    print(f"  ENTERPRISE:  {make_token('enterprise')}")
    print()

    agent_os.serve(app="04_tiered_model_factory:app", port=7777, reload=True)
