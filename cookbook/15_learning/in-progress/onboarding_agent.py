"""
Onboarding Agent
================
An agent that helps new team members get up to speed by leveraging
team knowledge and tracking their progress.

Demonstrates:
- Learned knowledge for team documentation
- User profile to track onboarding progress
- Session context for guided learning paths

Run:
    python cookbook/15_learning/patterns/onboarding_agent.py
"""

from dataclasses import dataclass, field
from typing import List, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.learn.schemas import UserProfile
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="onboarding_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


# ============================================================================
# Custom Schema: New Hire Profile
# ============================================================================
@dataclass
class NewHireProfile(UserProfile):
    """Profile tracking new hire onboarding progress."""

    role: Optional[str] = field(
        default=None,
        metadata={"description": "Job role (e.g., Software Engineer, Product Manager)"},
    )
    team: Optional[str] = field(
        default=None, metadata={"description": "Team assignment"}
    )
    start_date: Optional[str] = field(
        default=None, metadata={"description": "Start date at company"}
    )
    manager: Optional[str] = field(
        default=None, metadata={"description": "Direct manager name"}
    )
    onboarding_stage: Optional[str] = field(
        default=None,
        metadata={
            "description": "Current stage: orientation | training | ramping | complete"
        },
    )
    completed_topics: Optional[List[str]] = field(
        default=None, metadata={"description": "Topics they've completed"}
    )
    tech_background: Optional[List[str]] = field(
        default=None, metadata={"description": "Technologies they already know"}
    )


# ============================================================================
# Onboarding Agent
# ============================================================================
onboarding_agent = Agent(
    name="Onboarding Buddy",
    agent_id="onboarding-buddy",
    model=model,
    db=db,
    instructions="""\
You are an onboarding buddy helping new team members get up to speed.

Your approach:
1. Understand their background and role
2. Guide them through relevant documentation
3. Answer questions about processes and tools
4. Track their progress and adapt accordingly

Onboarding path:
1. **Week 1**: Company overview, team intro, dev environment setup
2. **Week 2**: Codebase walkthrough, coding conventions, PR process
3. **Week 3**: Architecture deep-dive, key services
4. **Week 4**: First project assignment, ongoing support

For each topic:
- Check if they have relevant background
- Explain concepts at the right level
- Point to relevant documentation
- Suggest hands-on exercises

Track their progress:
- Update their completed_topics as they learn
- Move them through onboarding_stage
- Remember their questions for follow-up

Be encouraging and patient. Starting a new job is overwhelming!
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            schema=NewHireProfile,
            enable_agent_tools=True,
            agent_can_update_memories=True,
            agent_can_update_profile=True,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,  # Track onboarding progress
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="onboarding",
            enable_agent_tools=True,
            agent_can_search=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Setup: Seed Onboarding Knowledge
# ============================================================================
def seed_knowledge():
    """Seed the knowledge base with onboarding content."""
    user = "admin@company.com"

    topics = [
        "Dev Environment: Use VS Code with our extension pack. Clone repos from "
        "GitHub Enterprise. Run ./scripts/setup.sh for initial configuration.",
        "Git Workflow: We use trunk-based development. Create feature branches "
        "from main, keep PRs small (<400 lines), require 2 approvals. Always "
        "squash merge.",
        "Code Style: Python code follows Black formatting. TypeScript uses "
        "Prettier + ESLint. Run pre-commit hooks before pushing.",
        "Architecture: We're a microservices shop. API Gateway routes to services. "
        "Each service owns its data. Use async messaging for cross-service comms.",
        "Incident Response: For P1 incidents, page the on-call (PagerDuty). "
        "Create an incident channel in Slack. Post updates every 30 minutes.",
        "Meetings: Daily standup at 10am PT. Sprint planning Mondays. "
        "Retros every other Friday. 1:1s are weekly with your manager.",
    ]

    print("Seeding onboarding knowledge...")
    for topic in topics:
        onboarding_agent.print_response(
            f"Save this onboarding information: {topic}",
            user_id=user,
            session_id="seed_session",
            stream=False,
        )
    print("✅ Knowledge seeded\n")


# ============================================================================
# Demo
# ============================================================================
def demo():
    """Demonstrate the onboarding agent."""
    print("=" * 60)
    print("Onboarding Agent Demo")
    print("=" * 60)

    # Seed knowledge first
    seed_knowledge()

    user = "new_hire@company.com"

    # New hire introduction
    print("\n--- New Hire Introduction ---\n")
    onboarding_agent.print_response(
        "Hi! I'm Jordan, just started today as a Software Engineer on the "
        "Platform team. My manager is Sarah. I have 5 years of Python experience "
        "but I'm new to microservices architecture.",
        user_id=user,
        session_id="onboarding_day1",
        stream=True,
    )

    # First question
    print("\n--- First Question ---\n")
    onboarding_agent.print_response(
        "What's the first thing I should set up on my laptop?",
        user_id=user,
        session_id="onboarding_day1",
        stream=True,
    )

    # Architecture question
    print("\n--- Architecture Question ---\n")
    onboarding_agent.print_response(
        "Can you explain how our services communicate? I'm used to monoliths.",
        user_id=user,
        session_id="onboarding_day2",
        stream=True,
    )

    # Progress check
    print("\n--- Progress Check ---\n")
    onboarding_agent.print_response(
        "What have I covered so far and what should I focus on next?",
        user_id=user,
        session_id="onboarding_day3",
        stream=True,
    )


if __name__ == "__main__":
    demo()
