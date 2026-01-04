"""
User Profile: Background Extraction
===================================
Automatic profile extraction after conversations.

In BACKGROUND mode (default), the LearningMachine automatically:
1. Analyzes each conversation
2. Extracts user information
3. Updates the profile

This happens after the response is generated, so it doesn't
add latency to the user experience.

Run:
    python cookbook/15_learning/user_profile/01_background_extraction.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIChat

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

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
            mode=LearningMode.BACKGROUND,  # Automatic extraction
            enable_add_memory=True,  # Can add new memories
            enable_update_memory=True,  # Can update existing
            enable_update_profile=True,  # Can update name, etc.
        ),
    ),
    markdown=True,
)


# ============================================================================
# Helper: Show profile
# ============================================================================
def show_profile(user_id: str) -> None:
    """Display the current profile state."""
    from rich.pretty import pprint

    store = agent.learning.user_profile_store
    profile = store.get(user_id=user_id) if store else None
    if profile:
        print("\n📋 Profile:")
        pprint(profile)
    else:
        print("\n📋 No profile yet")


# ============================================================================
# Demo: Gradual Profile Building
# ============================================================================
def demo_gradual_extraction():
    """Show profile building over multiple conversations."""
    print("=" * 60)
    print("Demo: Gradual Profile Extraction")
    print("=" * 60)

    user = "gradual@example.com"

    # Conversation 1: Basic introduction
    print("\n--- Conversation 1: Introduction ---\n")
    agent.print_response(
        "Hi! I'm Marcus, nice to meet you.",
        user_id=user,
        session_id="conv_1",
        stream=True,
    )
    show_profile(user)

    # Conversation 2: Share work context
    print("\n--- Conversation 2: Work context ---\n")
    agent.print_response(
        "I'm a senior engineer at Stripe, focusing on payment systems.",
        user_id=user,
        session_id="conv_2",
        stream=True,
    )
    show_profile(user)

    # Conversation 3: Share preferences
    print("\n--- Conversation 3: Preferences ---\n")
    agent.print_response(
        "When explaining things, I prefer code examples over long explanations. "
        "I'm very familiar with Python and Go.",
        user_id=user,
        session_id="conv_3",
        stream=True,
    )
    show_profile(user)

    # Conversation 4: Personal detail
    print("\n--- Conversation 4: Personal info ---\n")
    agent.print_response(
        "By the way, most people call me Marc.",
        user_id=user,
        session_id="conv_4",
        stream=True,
    )
    show_profile(user)


# ============================================================================
# Demo: Implicit Extraction
# ============================================================================
def demo_implicit_extraction():
    """Show extraction from natural conversation (not explicit statements)."""
    print("\n" + "=" * 60)
    print("Demo: Implicit Extraction")
    print("=" * 60)

    user = "implicit@example.com"

    # Information embedded in a question
    print("\n--- Information in question ---\n")
    agent.print_response(
        "As someone who's been doing machine learning for 8 years, "
        "I'm curious what you think about the latest transformers paper.",
        user_id=user,
        session_id="implicit_1",
        stream=True,
    )
    show_profile(user)

    # Preferences shown by correction
    print("\n--- Preferences via correction ---\n")
    agent.print_response(
        "That explanation is way too basic. Remember, I have a PhD in CS. "
        "Can you give me the technical details?",
        user_id=user,
        session_id="implicit_2",
        stream=True,
    )
    show_profile(user)


# ============================================================================
# Demo: What Gets Extracted
# ============================================================================
def demo_extraction_types():
    """Show different types of information that get extracted."""
    print("\n" + "=" * 60)
    print("Demo: Types of Extracted Information")
    print("=" * 60)

    user = "types@example.com"

    print("\n--- Rich information dump ---\n")
    agent.print_response(
        "A bit about me: I'm Taylor (they/them), a product designer at Figma. "
        "I work remotely from Portland, OR. I'm really into minimalist design "
        "and I hate when documentation has too much jargon. "
        "I've been using Figma for 5 years and React for 3. "
        "I usually work late nights, so I prefer async communication.",
        user_id=user,
        session_id="types_1",
        stream=True,
    )
    show_profile(user)

    print("\n🔍 Notice what was extracted:")
    print("   - Name: Taylor")
    print("   - Preferred name/pronouns: they/them")
    print("   - Work: Product designer at Figma")
    print("   - Location: Portland, OR")
    print("   - Preferences: minimalist, no jargon, async communication")
    print("   - Skills: Figma (5yr), React (3yr)")
    print("   - Work style: late nights")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_gradual_extraction()
    demo_implicit_extraction()
    demo_extraction_types()

    print("\n" + "=" * 60)
    print("✅ BACKGROUND mode extracts information automatically")
    print("   - No tools needed")
    print("   - Runs after response")
    print("   - Extracts from natural conversation")
    print("=" * 60)
