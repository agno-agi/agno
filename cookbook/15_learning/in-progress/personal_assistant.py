"""
Personal Assistant Agent
========================
A learning-enabled personal assistant that remembers preferences,
tracks conversations, and learns from interactions.

Demonstrates:
- User profile for personal preferences
- Session context for conversation continuity
- Learned knowledge for reusable insights

Run:
    python cookbook/15_learning/patterns/personal_assistant.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearningMachine,
    LearningMode,
    UserProfileConfig,
    SessionContextConfig,
    LearnedKnowledgeConfig,
)
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
        table_name="personal_assistant_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Personal Assistant Agent
# ============================================================================
personal_assistant = Agent(
    name="Personal Assistant",
    agent_id="personal-assistant",
    model=model,
    db=db,
    instructions="""\
You are a thoughtful personal assistant who remembers user preferences
and learns from every interaction.

Your approach:
1. Remember personal details, preferences, and communication style
2. Track ongoing conversations and tasks
3. Learn patterns that help you assist better over time

Key behaviors:
- Greet users by their preferred name
- Adapt tone to match their communication style
- Remember context from previous sessions
- Proactively apply learnings to improve responses

When you notice something worth remembering:
- Personal preferences → Save to user profile
- Reusable patterns → Save as learnings
- Current task context → Session handles automatically

Be warm, helpful, and anticipate needs based on what you know.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            enable_add_memory=True,
            enable_update_memory=True,
            enable_update_profile=True,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="personal_assistant",
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo
# ============================================================================
def demo():
    """Demonstrate the personal assistant."""
    user = "demo_user@example.com"

    print("=" * 60)
    print("Personal Assistant Demo")
    print("=" * 60)

    # Introduction
    print("\n--- Introduction ---\n")
    personal_assistant.print_response(
        "Hi! I'm Alex. I work in product management at a tech startup. "
        "I prefer concise communication and I'm usually pretty busy. "
        "Morning meetings don't work well for me - I'm a night owl.",
        user_id=user,
        session_id="intro_session",
        stream=True,
    )

    # Task assistance
    print("\n--- Task Request ---\n")
    personal_assistant.print_response(
        "Can you help me prepare for a product review meeting? "
        "I need to present our Q4 roadmap.",
        user_id=user,
        session_id="prep_session",
        stream=True,
    )

    # Follow-up in same session
    print("\n--- Follow-up ---\n")
    personal_assistant.print_response(
        "The main features are: AI search, team collaboration, and mobile app. "
        "What's a good structure for the presentation?",
        user_id=user,
        session_id="prep_session",
        stream=True,
    )

    # New session, test memory
    print("\n--- New Session (Memory Test) ---\n")
    personal_assistant.print_response(
        "Hey, I need to schedule a meeting. What times should I avoid?",
        user_id=user,
        session_id="schedule_session",
        stream=True,
    )


if __name__ == "__main__":
    demo()
