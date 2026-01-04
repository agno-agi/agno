"""
Sales Agent
===========
A CRM-aware sales assistant that tracks prospects, companies,
and deal progress.

Demonstrates:
- Entity memory for companies and contacts
- User profile for sales rep preferences
- Session context for deal conversations

Run:
    python cookbook/15_learning/patterns/sales_agent.py
"""

from dataclasses import dataclass, field
from typing import Optional, List

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    LearningMachine,
    LearningMode,
    UserProfileConfig,
    SessionContextConfig,
    EntityMemoryConfig,
)
from agno.learn.schemas import UserProfile
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")


# ============================================================================
# Custom Schema: Sales Rep Profile
# ============================================================================
@dataclass
class SalesRepProfile(UserProfile):
    """Profile for sales representatives."""

    territory: Optional[str] = field(
        default=None,
        metadata={"description": "Sales territory (e.g., West Coast, EMEA)"}
    )
    quota: Optional[str] = field(
        default=None,
        metadata={"description": "Quarterly quota amount"}
    )
    product_specialty: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Products they specialize in"}
    )
    preferred_crm: Optional[str] = field(
        default=None,
        metadata={"description": "CRM system preference (Salesforce, HubSpot, etc.)"}
    )


# ============================================================================
# Sales Agent
# ============================================================================
sales_agent = Agent(
    name="Sales Assistant",
    agent_id="sales-assistant",
    model=model,
    db=db,
    instructions="""\
You are a sales assistant helping reps manage their pipeline and close deals.

Your capabilities:
1. Track companies and contacts (entity memory)
2. Remember deal context and progress (session context)
3. Learn from successful patterns (your knowledge)

When tracking prospects:
- Create entities for companies and key contacts
- Record facts: budget, timeline, decision makers, tech stack
- Record events: meetings, demos, proposals sent
- Track relationships: who reports to whom, key influencers

During deal conversations:
- Maintain context on the current opportunity
- Track next steps and action items
- Flag risks or blockers

Sales best practices to apply:
- Always identify the decision maker and budget holder
- Understand the buying timeline
- Map out the competitive landscape
- Track all stakeholder interactions
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            schema=SalesRepProfile,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="sales",  # Sales team shared namespace
            enable_agent_tools=True,
            agent_can_create_entity=True,
            agent_can_search_entities=True,
            enable_add_fact=True,
            enable_add_event=True,
            enable_add_relationship=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo
# ============================================================================
def demo():
    """Demonstrate the sales agent."""
    user = "sales_rep@company.com"

    print("=" * 60)
    print("Sales Agent Demo")
    print("=" * 60)

    # Log a prospect
    print("\n--- Log New Prospect ---\n")
    sales_agent.print_response(
        "Just had a great discovery call with TechCorp. They're a Series B "
        "startup doing $10M ARR. Spoke with Sarah Chen (VP Engineering) and "
        "Mike Johnson (CTO). They need our API platform - budget is around $200K. "
        "Timeline is Q2. Main competition is FastAPI Cloud. Please track this.",
        user_id=user,
        session_id="techcorp_deal",
        stream=True,
    )

    # Follow-up meeting
    print("\n--- Follow-up Meeting ---\n")
    sales_agent.print_response(
        "Had a follow-up with TechCorp. Sarah is the champion but Mike makes "
        "the final call. They want a POC first. I'm scheduling a technical demo "
        "for next week. Sarah mentioned they're also talking to Postman.",
        user_id=user,
        session_id="techcorp_deal",
        stream=True,
    )

    # Query pipeline
    print("\n--- Query Pipeline ---\n")
    sales_agent.print_response(
        "What do we know about TechCorp? Who are the key stakeholders?",
        user_id=user,
        session_id="pipeline_review",
        stream=True,
    )

    # Deal status
    print("\n--- Deal Status ---\n")
    sales_agent.print_response(
        "Give me a summary of the TechCorp deal. What are the next steps "
        "and any risks I should be aware of?",
        user_id=user,
        session_id="techcorp_deal",
        stream=True,
    )


if __name__ == "__main__":
    demo()
