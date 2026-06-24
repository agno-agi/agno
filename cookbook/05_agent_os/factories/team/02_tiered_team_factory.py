"""Tiered Team Factory -- team size and model quality based on subscription.

Free-tier tenants get a smaller team with a cheaper model.
Enterprise tenants get a larger team with the best model and extra capabilities.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/factories/team/02_tiered_team_factory.py

Test:
    # Free tier (2 members, cheaper model)
    curl -X POST http://localhost:7777/teams/research-team/runs \
        -H "Authorization: Bearer <FREE_TOKEN>" \
        -F 'message=Research the impact of AI on healthcare' \
        -F 'stream=false'

    # Enterprise tier (3 members, best model)
    curl -X POST http://localhost:7777/teams/research-team/runs \
        -H "Authorization: Bearer <ENTERPRISE_TOKEN>" \
        -F 'message=Research the impact of AI on healthcare' \
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
from agno.team.factory import TeamFactory
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JWT_SECRET = "a-string-secret-at-least-256-bits-long"

db = PostgresDb(
    id="tiered-team-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

TIER_MODELS = {
    "free": "gpt-4.1-mini",
    "enterprise": "gpt-5.4",
}

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_research_team(ctx: RequestContext) -> Team:
    """Build a research team whose size and model depend on subscription tier."""
    claims = ctx.trusted.claims
    tier = claims.get("tier", "free")
    model_id = TIER_MODELS.get(tier, TIER_MODELS["free"])

    researcher = Agent(
        name="Researcher",
        role="Find and summarize information",
        model=OpenAIResponses(id=model_id),
        instructions="Research the topic thoroughly. Cite key findings.",
    )

    writer = Agent(
        name="Writer",
        role="Draft the final report",
        model=OpenAIResponses(id=model_id),
        instructions="Write a clear, well-structured report based on the research.",
    )

    members = [researcher, writer]

    # Enterprise gets an extra reviewer
    if tier == "enterprise":
        reviewer = Agent(
            name="Reviewer",
            role="Review and critique the report",
            model=OpenAIResponses(id=model_id),
            instructions="Review the report for accuracy, gaps, and clarity. Suggest improvements.",
        )
        members.append(reviewer)

    return Team(
        name="Research Team",
        model=OpenAIResponses(id=model_id),
        members=members,
        db=db,
        instructions=[
            "Coordinate the research process.",
            "The Researcher finds information, the Writer drafts the report.",
        ]
        + (
            ["The Reviewer checks quality before finalizing."]
            if tier == "enterprise"
            else []
        ),
        markdown=True,
    )


research_team_factory = TeamFactory(
    db=db,
    id="research-team",
    name="Research Team",
    description="Research team -- size and model quality scale with subscription tier",
    factory=build_research_team,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="tiered-team-demo",
    description="Demo: tiered team factory with JWT",
    teams=[research_team_factory],
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

    agent_os.serve(app="02_tiered_team_factory:app", port=7777, reload=True)
