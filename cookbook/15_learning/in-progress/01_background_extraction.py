"""
User Profile: Background Extraction
===================================
Automatic profile extraction from conversations.

BACKGROUND mode extracts user information automatically after each
conversation. The user doesn't need to ask the agent to remember
anything - it just happens.

What gets extracted:
- Name and preferred name
- Work context (company, role)
- Preferences and interests
- Technical expertise
- Communication style

Run:
    python cookbook/15_learning/user_profile/01_background_extraction.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with BACKGROUND extraction
# ============================================================================
agent = Agent(
    name="Background Extraction Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,  # Auto-extract after each response
            # What operations to enable during extraction:
            enable_add_memory=True,      # Add new observations
            enable_update_memory=True,   # Update existing ones
            enable_delete_memory=False,  # Don't auto-delete (safer)
            enable_update_profile=True,  # Update name, preferred_name
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Incremental Profile Building
# ============================================================================
def demo_incremental_building():
    """Show how profiles build up over multiple conversations."""
    print("=" * 60)
    print("Demo: Incremental Profile Building")
    print("=" * 60)

    user = "bg_extract_demo@example.com"

    # Conversation 1: Basic introduction
    print("\n--- Conversation 1: Introduction ---\n")
    agent.print_response(
        "Hi! I'm Sarah Chen, I'm a senior ML engineer at Stripe.",
        user_id=user,
        session_id="conv_1",
        stream=True,
    )

    # Conversation 2: More context
    print("\n--- Conversation 2: Work context ---\n")
    agent.print_response(
        "I mainly work on fraud detection models. Python and PyTorch are my bread and butter.",
        user_id=user,
        session_id="conv_2",
        stream=True,
    )

    # Conversation 3: Preferences
    print("\n--- Conversation 3: Preferences ---\n")
    agent.print_response(
        "I prefer detailed technical explanations with code examples. "
        "Skip the high-level overviews - I can handle the complexity.",
        user_id=user,
        session_id="conv_3",
        stream=True,
    )

    # Conversation 4: Check what was remembered
    print("\n--- Conversation 4: Memory check ---\n")
    agent.print_response(
        "What do you know about me? Be specific.",
        user_id=user,
        session_id="conv_4",
        stream=True,
    )


# ============================================================================
# Demo: Rich Extraction
# ============================================================================
def demo_rich_extraction():
    """Show extraction from a rich, information-dense conversation."""
    print("\n" + "=" * 60)
    print("Demo: Rich Extraction")
    print("=" * 60)

    user = "rich_extract_demo@example.com"

    print("\n--- Information-dense message ---\n")
    agent.print_response(
        "Hey, I'm Marcus (but call me Marc). I'm the founding engineer at "
        "a Series A startup called DataPipe. We're building real-time ETL "
        "infrastructure. I'm obsessed with Rust and systems programming. "
        "I work weird hours (usually 11pm-3am) because that's when I'm most "
        "productive. I hate long meetings and prefer async communication. "
        "My timezone is PST.",
        user_id=user,
        session_id="rich_conv",
        stream=True,
    )

    print("\n--- Verify extraction ---\n")
    agent.print_response(
        "Summarize everything you remember about me.",
        user_id=user,
        session_id="verify_conv",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_incremental_building()
    demo_rich_extraction()

    print("\n" + "=" * 60)
    print("✅ Background extraction captures user info automatically")
    print("   No explicit 'remember this' needed - it just works.")
    print("=" * 60)
