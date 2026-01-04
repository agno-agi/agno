"""
Entity Memory: Background Extraction
====================================
Automatic entity extraction from conversations.

In BACKGROUND mode, entities are extracted automatically after
each conversation. No explicit "save this" needed.

The extraction looks for:
- Named entities (companies, people, products, projects)
- Facts about those entities
- Events involving those entities
- Relationships between entities

This is great for:
- Passive knowledge accumulation
- CRM-style tracking
- Meeting note processing

Run:
    python cookbook/15_learning/entity_memory/04_background_extraction.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, EntityMemoryConfig, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with Background Entity Extraction
# ============================================================================
agent = Agent(
    name="Background Entity Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant. Have natural conversations.

Behind the scenes, you automatically extract and remember information
about companies, people, projects, and other entities mentioned.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.BACKGROUND,  # Auto-extract
            namespace="global",
            # Enable all extraction operations
            enable_create_entity=True,
            enable_update_entity=True,
            enable_add_fact=True,
            enable_add_event=True,
            enable_add_relationship=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Natural Conversation
# ============================================================================
def demo_natural_conversation():
    """Show automatic extraction from natural conversation."""
    print("=" * 60)
    print("Demo: Natural Conversation → Automatic Extraction")
    print("=" * 60)

    user = "bg_entity_demo@example.com"
    session = "natural_session"

    # Natural conversation mentioning entities
    print("\n--- Natural conversation ---\n")
    agent.print_response(
        "I just got back from a meeting with the DataFlow team. "
        "They're a startup building real-time analytics. "
        "Their CEO, Maria Chen, was really impressive. "
        "They use Kafka for streaming and Snowflake for storage. "
        "They're planning to launch their enterprise tier next month.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Later, query what was extracted
    print("\n--- Query extracted entities ---\n")
    agent.print_response(
        "What do you know about DataFlow?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: Meeting Notes
# ============================================================================
def demo_meeting_notes():
    """Show extraction from meeting notes."""
    print("\n" + "=" * 60)
    print("Demo: Meeting Notes → Entity Extraction")
    print("=" * 60)

    user = "meeting_notes@example.com"
    session = "meeting_session"

    # Dump meeting notes
    print("\n--- Meeting notes ---\n")
    agent.print_response(
        """Here are my notes from today's partner meeting:

        - Met with Acme Corp (potential customer)
        - Attendees: John Smith (VP Engineering), Lisa Wang (CTO)
        - Acme is migrating from Oracle to PostgreSQL
        - They need our data pipeline tools
        - Budget approved: $200K annually
        - Timeline: Want to start pilot in 6 weeks
        - John mentioned they also work with CloudVendor for hosting
        - Next steps: Send proposal by Friday

        Can you summarize the key points?""",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query specific entities
    print("\n--- Query: Acme Corp details ---\n")
    agent.print_response(
        "What do we know about Acme Corp and their technical needs?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )

    print("\n--- Query: People at Acme ---\n")
    agent.print_response(
        "Who did we meet at Acme Corp?",
        user_id=user,
        session_id=session + "_3",
        stream=True,
    )


# ============================================================================
# Demo: Incremental Learning
# ============================================================================
def demo_incremental():
    """Show how entity knowledge builds over time."""
    print("\n" + "=" * 60)
    print("Demo: Incremental Entity Learning")
    print("=" * 60)

    user = "incremental@example.com"
    session = "incr_session"

    # First mention
    print("\n--- First mention ---\n")
    agent.print_response(
        "TechGiant is a Fortune 500 company in the tech sector.",
        user_id=user,
        session_id=session + "_1",
        stream=True,
    )

    # More details
    print("\n--- More details ---\n")
    agent.print_response(
        "TechGiant has about 50,000 employees worldwide. "
        "They're headquartered in Seattle.",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )

    # Recent event
    print("\n--- Recent event ---\n")
    agent.print_response(
        "TechGiant just announced they're acquiring CloudSmall for $2B.",
        user_id=user,
        session_id=session + "_3",
        stream=True,
    )

    # Leadership info
    print("\n--- Leadership ---\n")
    agent.print_response(
        "TechGiant's new CEO is Robert Park. He joined last quarter.",
        user_id=user,
        session_id=session + "_4",
        stream=True,
    )

    # Full picture
    print("\n--- Full entity picture ---\n")
    agent.print_response(
        "Give me everything we know about TechGiant.",
        user_id=user,
        session_id=session + "_5",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_natural_conversation()
    demo_meeting_notes()
    demo_incremental()

    print("\n" + "=" * 60)
    print("✅ Background mode extracts entities automatically")
    print("   No explicit 'save this' needed")
    print("   Knowledge builds incrementally over time")
    print("=" * 60)
