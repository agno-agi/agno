"""
Pattern: Personal Assistant with Learning
=========================================
A personal assistant that learns about the user over time.

This pattern combines:
- User Profile: Preferences, routines, communication style
- Session Context: Current conversation state
- Entity Memory: Contacts, projects, places, events

The assistant becomes increasingly personalized without being asked.

See also: 01_basics/ for individual store examples.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    EntityMemoryConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


def create_personal_assistant(user_id: str, session_id: str) -> Agent:
    """Create a personal assistant for a specific user."""
    return Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        db=db,
        instructions=(
            "You are a helpful personal assistant. "
            "Remember user preferences without being asked. "
            "Keep track of important people and events in their life."
        ),
        learning=LearningMachine(
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.ALWAYS,
                namespace=f"user:{user_id}:personal",
            ),
        ),
        user_id=user_id,
        session_id=session_id,
        markdown=True,
    )


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from rich.pretty import pprint

    user_id = "alex@example.com"

    # Conversation 1: Introduction
    print("\n" + "=" * 60)
    print("CONVERSATION 1: Introduction")
    print("=" * 60 + "\n")

    agent = create_personal_assistant(user_id, "conv_1")
    agent.print_response(
        "Hi! I'm Alex Chen. I work as a product manager at Stripe. "
        "I prefer concise responses. My sister Sarah is visiting next month.",
        stream=True,
    )
    agent.learning_machine.user_profile_store.print(user_id=user_id)
    print("\n--- Entities ---")
    pprint(agent.learning_machine.entity_memory_store.search(query="sarah", limit=10))

    # Conversation 2: New session (demonstrates memory)
    print("\n" + "=" * 60)
    print("CONVERSATION 2: New session (memory test)")
    print("=" * 60 + "\n")

    agent = create_personal_assistant(user_id, "conv_2")
    agent.print_response(
        "What do you remember about me and my sister?",
        stream=True,
    )

    # Conversation 3: Planning something
    print("\n" + "=" * 60)
    print("CONVERSATION 3: Planning activity")
    print("=" * 60 + "\n")

    agent = create_personal_assistant(user_id, "conv_3")
    agent.print_response(
        "Help me plan activities for Sarah's visit. She likes hiking.",
        stream=True,
    )
    agent.learning_machine.session_context_store.print(session_id="conv_3")
