"""
Pattern: Support Agent
======================
Customer support with memory and knowledge.

This agent demonstrates:
- Custom user profile schema for support context
- Entity memory for tracking customer accounts
- Learned knowledge for support patterns and solutions
- Session context for multi-turn support tickets

Run standalone:
    python cookbook/15_learning/patterns/support_agent.py

Or via AgentOS:
    python cookbook/15_learning/run.py
"""

from dataclasses import dataclass, field
from typing import List, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    EntityMemoryConfig,
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


# ============================================================================
# Custom Schema: Support Customer Profile
# ============================================================================
@dataclass
class SupportCustomerProfile(UserProfile):
    """Extended profile for support customers."""

    company: Optional[str] = field(
        default=None, metadata={"description": "Customer's company name"}
    )
    plan_tier: Optional[str] = field(
        default=None, metadata={"description": "Subscription: free | pro | enterprise"}
    )
    expertise_level: Optional[str] = field(
        default=None,
        metadata={"description": "Technical level: beginner | intermediate | expert"},
    )
    primary_use_case: Optional[str] = field(
        default=None, metadata={"description": "Main use case for our product"}
    )
    integrations: Optional[List[str]] = field(
        default=None, metadata={"description": "Integrations they use"}
    )
    previous_issues: Optional[List[str]] = field(
        default=None, metadata={"description": "Summary of past support issues"}
    )


# ============================================================================
# Knowledge Base for Support Patterns
# ============================================================================
support_knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="support_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Support Agent
# ============================================================================
support_agent = Agent(
    name="Support Agent",
    agent_id="support-agent",
    model=model,
    db=db,
    instructions="""\
You are a customer support agent for a SaaS product.

Your capabilities:
1. **Customer Memory**: I remember each customer's history, plan, and preferences
2. **Account Tracking**: I track customer companies and their technical setup
3. **Knowledge Base**: I learn from resolved tickets to help future customers
4. **Session Tracking**: I maintain context throughout a support conversation

Support Guidelines:
- Be empathetic and patient
- Ask clarifying questions when needed
- Search for similar issues before escalating
- Document solutions for future reference

When you solve a tricky issue:
- Consider saving it as a learning for similar future cases

When gathering customer info:
- Note their plan tier (affects available features)
- Note their expertise level (affects explanation depth)
- Track integrations (common source of issues)
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=support_knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            schema=SupportCustomerProfile,
        ),
        session_context=SessionContextConfig(
            enable_planning=False,  # Support tickets don't need planning
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="support",  # Shared with support team
            enable_agent_tools=True,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="support",
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Support Interaction
# ============================================================================
def demo_support():
    """Demonstrate a support interaction."""
    print("=" * 60)
    print("Demo: Support Agent")
    print("=" * 60)

    user = "customer@techstartup.com"
    session = "ticket_001"

    # Initial contact
    print("\n--- Customer opens ticket ---\n")
    support_agent.print_response(
        "Hi, I'm having trouble with the API integration. "
        "I'm getting 401 errors even though my API key looks correct. "
        "We're on the pro plan and using the Python SDK.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Troubleshooting
    print("\n--- Troubleshooting ---\n")
    support_agent.print_response(
        "I just checked and the key starts with 'sk_test_'. "
        "I'm calling the production endpoint though.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Resolution
    print("\n--- Resolution ---\n")
    support_agent.print_response(
        "Oh! I was using a test key with production. That fixed it! "
        "Thanks so much for your help.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Returning Customer
# ============================================================================
def demo_returning():
    """Show memory of returning customers."""
    print("\n" + "=" * 60)
    print("Demo: Returning Customer")
    print("=" * 60)

    user = "customer@techstartup.com"  # Same customer
    session = "ticket_002"  # New ticket

    print("\n--- Customer returns with new issue ---\n")
    support_agent.print_response(
        "Hey, me again. Now I'm having issues with rate limiting. "
        "We're making about 1000 requests per minute.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Knowledge Application
# ============================================================================
def demo_knowledge():
    """Show applying learned knowledge."""
    print("\n" + "=" * 60)
    print("Demo: Applying Support Knowledge")
    print("=" * 60)

    user = "newcustomer@example.com"
    session = "ticket_003"

    # First, seed some knowledge
    print("\n--- (Setup: Save a common issue resolution) ---\n")
    support_agent.print_response(
        "Save this as a support pattern: When customers report 401 errors "
        "with test keys in production, the issue is almost always using "
        "sk_test_ keys instead of sk_live_ keys. Quick fix: Check key prefix.",
        user_id="support_admin@company.com",
        session_id="admin_session",
        stream=True,
    )

    # New customer with similar issue
    print("\n--- New customer with similar issue ---\n")
    support_agent.print_response(
        "I'm getting 401 errors on my API calls. Using Python SDK. "
        "Not sure what's wrong.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_support()
    demo_returning()
    demo_knowledge()

    print("\n" + "=" * 60)
    print("✅ Support Agent with full learning capabilities")
    print("   - Remembers customers and their context")
    print("   - Tracks accounts and integrations")
    print("   - Learns from resolved tickets")
    print("=" * 60)
