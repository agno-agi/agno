"""
Choose Model Configuration from a Trusted Tier
==============================================

Use a verified subscription claim to choose low or high reasoning effort for
the approved gpt-5.5 model without trusting client-controlled factory input.

Prerequisites: none beyond OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/21_factories/04_tiered_model.py
Try: In another terminal, rerun this file with --demo
"""

import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import httpx
import jwt
from agno.agent import Agent, AgentFactory
from agno.db.sqlite import SqliteDb
from agno.factory import RequestContext, TrustedContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware

# ---------------------------------------------------------------------------
# Create Tiered Model Policy
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
JWT_SECRET = "tiered-model-demo-secret-with-at-least-32-bytes"
ReasoningEffort = Literal["low", "high"]
TIER_REASONING: dict[str, ReasoningEffort] = {
    "standard": "low",
    "enterprise": "high",
}

db = SqliteDb(
    id="tiered-model-factory-db",
    db_file="tmp/21_factories_tiered_model.db",
)


def build_tiered_agent(ctx: RequestContext) -> Agent:
    """Build one model configuration from a verified subscription tier."""
    tier = str(ctx.trusted.claims.get("tier", "standard"))
    effort = TIER_REASONING.get(tier, TIER_REASONING["standard"])
    return Agent(
        model=OpenAIResponses(id="gpt-5.5", reasoning_effort=effort),
        instructions=(
            f"The verified subscription tier is {tier}. "
            f"Use {effort} reasoning effort and answer concisely."
        ),
    )


tiered_factory = AgentFactory(
    id="tiered-assistant",
    name="Tiered Assistant",
    description="Selects an approved model configuration from a trusted tier.",
    db=db,
    factory=build_tiered_agent,
)

agent_os = AgentOS(
    id="tiered-model-factory-os",
    description="AgentOS selecting model configuration per verified request.",
    agents=[tiered_factory],
)
app = agent_os.get_app()
app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    validate=True,
    authorization=False,
)


def make_token(tier: str) -> str:
    """Create a short-lived demonstration token for one subscription tier."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": f"{tier}-subscriber",
            "tier": tier,
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def inspect_effort(tier: str) -> ReasoningEffort:
    """Resolve the factory and return the produced model's effort."""
    agent = tiered_factory.resolve(
        RequestContext(
            trusted=TrustedContext(claims={"tier": tier}),
        ),
        expected_type=Agent,
    )
    model = cast(OpenAIResponses, agent.model)
    return cast(ReasoningEffort, model.reasoning_effort)


def run_demo() -> None:
    """Inspect both tiers and run the enterprise configuration live."""
    standard_effort = inspect_effort("standard")
    enterprise_effort = inspect_effort("enterprise")
    if (standard_effort, enterprise_effort) != ("low", "high"):
        raise RuntimeError("Trusted tiers resolved to the wrong model policy")

    with httpx.Client(base_url=BASE_URL, timeout=90.0) as client:
        run_response = client.post(
            f"/agents/{tiered_factory.id}/runs",
            data={
                "message": "Explain in one sentence why trusted tiers matter.",
                "stream": "false",
            },
            headers={
                "Authorization": f"Bearer {make_token('enterprise')}",
            },
        )
        run_response.raise_for_status()
        run = run_response.json()
        if run["status"] != "COMPLETED":
            raise RuntimeError("The enterprise factory run did not complete")

    print(f"Standard: gpt-5.5 / {standard_effort}")
    print(f"Enterprise: gpt-5.5 / {enterprise_effort}")
    print(f"Run: {run['run_id']} -> {run['status']}")
    print(f"Response: {run['content']}")


# ---------------------------------------------------------------------------
# Run Factory AgentOS or Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        agent_os.serve(app=app)
