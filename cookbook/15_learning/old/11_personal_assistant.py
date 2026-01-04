"""
Personal Assistant
===========================================
A personal AI that deeply learns your preferences.

This agent maximizes personalization by:
- Learning communication preferences (tone, detail level, format)
- Remembering personal context (schedule, interests, goals)
- Adapting responses based on accumulated knowledge

The more you interact, the better it knows you.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# Personal Assistant Instructions
# =============================================================================
INSTRUCTIONS = """\
You are a Personal Assistant that deeply learns user preferences.

## Your Goals

1. **Remember everything relevant**
   - Personal preferences
   - Communication style
   - Interests and goals
   - Schedule patterns

2. **Adapt your responses**
   - Match their preferred tone
   - Adjust detail level
   - Use formats they like

3. **Be proactive**
   - Reference past conversations naturally
   - Anticipate needs based on patterns
   - Offer relevant suggestions

## Communication Adaptation

- If they prefer brief: Be concise
- If they like detail: Be thorough
- If they're casual: Match the tone
- If they're formal: Stay professional

Always feel like you truly know them.
"""

# =============================================================================
# Create Personal Assistant
# =============================================================================
assistant = Agent(
    name="Personal Assistant",
    model=OpenAIChat(id="gpt-4o"),
    instructions=INSTRUCTIONS,
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            enable_agent_tools=True,  # Also allow explicit saves (updated from enable_tool)
            instructions=(
                "Learn everything about this person: communication style, "
                "interests, work, family, preferences, schedule, goals, "
                "pet peeves, favorites. Be comprehensive."
            ),
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helpers
# =============================================================================
def show_what_i_know(user_id: str):
    """Show everything learned about a user."""
    profile = assistant.learning.stores["user_profile"].get(user_id=user_id)
    if profile and profile.memories:
        print(f"\n🧠 What I know about you:")
        for mem in profile.memories:
            print(f"   > {mem.get('content', mem)}")
    else:
        print("\n🧠 Still getting to know you...")
    print()


# =============================================================================
# Demo: Extended interaction to build deep profile
# =============================================================================
if __name__ == "__main__":
    user_id = "natalie@example.com"

    # --- Interaction 1: Introduction ---
    print("=" * 60)
    print("Interaction 1: Introduction")
    print("=" * 60)
    assistant.print_response(
        "Hi! I'm Natalie. I'm a product manager at a fintech startup. "
        "I'm pretty busy so I appreciate concise answers, but don't leave "
        "out important details.",
        user_id=user_id,
        session_id="personal_1",
        stream=True,
    )
    show_what_i_know(user_id)

    # --- Interaction 2: More context ---
    print("=" * 60)
    print("Interaction 2: More context")
    print("=" * 60)
    assistant.print_response(
        "I'm working on launching a new feature next month. It's a payment "
        "scheduling tool. I have to coordinate between engineering, design, "
        "and compliance. Pretty stressful!",
        user_id=user_id,
        session_id="personal_2",
        stream=True,
    )
    show_what_i_know(user_id)

    # --- Interaction 3: Personal info ---
    print("=" * 60)
    print("Interaction 3: Personal preferences")
    print("=" * 60)
    assistant.print_response(
        "By the way, I prefer bullet points over long paragraphs. "
        "And please no corporate jargon - I get enough of that at work.",
        user_id=user_id,
        session_id="personal_3",
        stream=True,
    )
    show_what_i_know(user_id)

    # --- Interaction 4: Test personalization ---
    print("=" * 60)
    print("Interaction 4: Test personalization")
    print("=" * 60)
    assistant.print_response(
        "What's a good framework for prioritizing features?",
        user_id=user_id,
        session_id="personal_4",
        stream=True,
    )

    # --- Interaction 5: Reference past context ---
    print("=" * 60)
    print("Interaction 5: Reference past context")
    print("=" * 60)
    assistant.print_response(
        "Can you help me plan out the next two weeks?",
        user_id=user_id,
        session_id="personal_5",
        stream=True,
    )

    # --- Final: What do you know about me? ---
    print("=" * 60)
    print("Final: What do you know about me?")
    print("=" * 60)
    assistant.print_response(
        "What do you know about me?",
        user_id=user_id,
        session_id="personal_6",
        stream=True,
    )
    show_what_i_know(user_id)
