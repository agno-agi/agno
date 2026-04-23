"""Tiered Workflow Factory -- pipeline depth based on subscription.

Free-tier tenants get a 2-step pipeline (draft + edit).
Enterprise tenants get a 3-step pipeline (research + draft + edit) with a better model.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/factories/workflow/02_tiered_workflow_factory.py

Test:
    # Free tier (2 steps, cheaper model)
    curl -X POST http://localhost:7777/workflows/article-pipeline/runs \
        -H "Authorization: Bearer <FREE_TOKEN>" \
        -F 'message=Write an article about remote work trends' \
        -F 'stream=false'

    # Enterprise tier (3 steps, best model)
    curl -X POST http://localhost:7777/workflows/article-pipeline/runs \
        -H "Authorization: Bearer <ENTERPRISE_TOKEN>" \
        -F 'message=Write an article about remote work trends' \
        -F 'stream=false'
"""

from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from agno.workflow.factory import WorkflowFactory
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JWT_SECRET = "a-string-secret-at-least-256-bits-long"

db = PostgresDb(
    id="tiered-workflow-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

TIER_MODELS = {
    "free": "gpt-4.1-mini",
    "enterprise": "gpt-5.4",
}

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_article_pipeline(ctx: RequestContext) -> Workflow:
    """Build an article pipeline whose depth depends on subscription tier."""
    claims = ctx.trusted.claims
    tier = claims.get("tier", "free")
    model_id = TIER_MODELS.get(tier, TIER_MODELS["free"])

    steps = []

    # Enterprise gets a research step first
    if tier == "enterprise":
        researcher = Agent(
            name="Researcher",
            model=OpenAIResponses(id=model_id),
            instructions="Research the topic thoroughly. Provide key facts, statistics, and sources.",
        )
        steps.append(
            Step(name="research", description="Research the topic", agent=researcher)
        )

    drafter = Agent(
        name="Drafter",
        model=OpenAIResponses(id=model_id),
        instructions="Write a well-structured article draft based on the input. Be thorough but readable.",
    )
    steps.append(
        Step(name="draft", description="Write the article draft", agent=drafter)
    )

    editor = Agent(
        name="Editor",
        model=OpenAIResponses(id=model_id),
        instructions="Edit the article for clarity, flow, and correctness. Output the final polished version.",
    )
    steps.append(Step(name="edit", description="Edit and finalize", agent=editor))

    return Workflow(
        name="Article Pipeline",
        description=f"Article pipeline ({len(steps)} steps, {tier} tier)",
        db=db,
        steps=steps,
    )


article_pipeline_factory = WorkflowFactory(
    db=db,
    id="article-pipeline",
    name="Article Pipeline",
    description="Article pipeline -- depth and model quality scale with subscription tier",
    factory=build_article_pipeline,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="tiered-workflow-demo",
    description="Demo: tiered workflow factory with JWT",
    workflows=[article_pipeline_factory],
)
app = agent_os.get_app()

app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    user_id_claim="sub",
    validate=False,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    def make_token(tier: str, user_id: str = "user_1") -> str:
        payload = {
            "sub": user_id,
            "tier": tier,
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iat": datetime.now(UTC),
        }
        return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

    print("Test tokens (valid for 24h):")
    print()
    print(f"  FREE:        {make_token('free')}")
    print(f"  ENTERPRISE:  {make_token('enterprise')}")
    print()

    agent_os.serve(app="02_tiered_workflow_factory:app", port=7777, reload=True)
