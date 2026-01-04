"""
Entity Memory: Background Extraction
====================================
Auto-extract entities from conversations.

In BACKGROUND mode, entities are automatically extracted
from conversations - no tools needed.

Run:
    python cookbook/15_learning/entity_memory/04_background_extraction.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIChat

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# ============================================================================
# Agent with Background Entity Extraction
# ============================================================================
agent = Agent(
    name="Background Entity Agent",
    model=model,
    db=db,
    instructions="You help users with business questions. Entities mentioned will be automatically tracked.",
    learning=LearningMachine(
        db=db,
        model=model,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.BACKGROUND,  # Auto-extract
            namespace="background_demo",
            enable_create_entity=True,
            enable_add_fact=True,
            enable_add_event=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Automatic Extraction
# ============================================================================
def demo_auto_extraction():
    """Show entities being extracted automatically."""
    print("=" * 60)
    print("Demo: Automatic Entity Extraction")
    print("=" * 60)

    user = "auto@example.com"

    # Natural conversation with entity mentions
    print("\n--- Natural conversation ---\n")
    agent.print_response(
        "I had a meeting with Acme Corp today. They're a fintech company "
        "based in New York. Their CTO, Sarah Johnson, mentioned they're "
        "launching a new product next month. They use React and Node.js.",
        user_id=user,
        session_id="auto_1",
        stream=True,
    )

    print("\n💡 Entities were extracted automatically in the background!")

    # Query what was learned
    print("\n--- Query extracted entities ---\n")
    agent.print_response(
        "What do we know about Acme Corp?",
        user_id=user,
        session_id="auto_2",
        stream=True,
    )


# ============================================================================
# Demo: Multi-Turn Extraction
# ============================================================================
def demo_multi_turn():
    """Show entity info accumulating across turns."""
    print("\n" + "=" * 60)
    print("Demo: Multi-Turn Entity Building")
    print("=" * 60)

    user = "multi@example.com"
    session = "multi_session"

    print("\n--- Turn 1: Basic info ---\n")
    agent.print_response(
        "I'm researching DataCo for a potential partnership.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n--- Turn 2: More details ---\n")
    agent.print_response(
        "I found out DataCo is a data analytics company founded in 2019. "
        "They have about 200 employees and are based in Austin, TX.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n--- Turn 3: Recent news ---\n")
    agent.print_response(
        "Just saw that DataCo raised a $40M Series B last week. "
        "Their CEO is Michael Chen.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n--- Query accumulated knowledge ---\n")
    agent.print_response(
        "Summarize everything we know about DataCo.",
        user_id=user,
        session_id=session + "_query",
        stream=True,
    )


# ============================================================================
# Background vs Agentic Comparison
# ============================================================================
def background_vs_agentic():
    """Compare background and agentic modes."""
    print("\n" + "=" * 60)
    print("Background vs Agentic Mode")
    print("=" * 60)
    print("""
BACKGROUND MODE:
   EntityMemoryConfig(mode=LearningMode.BACKGROUND)
   
   ✅ Automatic - no user action needed
   ✅ Captures everything mentioned
   ✅ Good for passive knowledge building
   
   ⚠️ May extract irrelevant entities
   ⚠️ Extra LLM call per message
   ⚠️ Less control over what's saved

AGENTIC MODE:
   EntityMemoryConfig(mode=LearningMode.AGENTIC)
   
   ✅ Agent decides what to save
   ✅ More precise/selective
   ✅ Transparent to user
   ✅ No hidden LLM calls
   
   ⚠️ Requires explicit saves
   ⚠️ May miss implicit mentions

RECOMMENDATION:
   - Use BACKGROUND for: CRM, research, knowledge graphs
   - Use AGENTIC for: precision, transparency, cost control
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_auto_extraction()
    demo_multi_turn()
    background_vs_agentic()

    print("\n" + "=" * 60)
    print("✅ BACKGROUND mode extracts entities automatically")
    print("   - No tools needed")
    print("   - Info accumulates over turns")
    print("   - Good for passive knowledge building")
    print("=" * 60)
