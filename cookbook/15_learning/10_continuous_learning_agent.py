"""
Continuous Learning Agent
==========================
An agent that learns from every interaction and improves over time.

The goal: Interaction 1000 is fundamentally better than interaction 1.

This agent demonstrates:
- Learns from EVERY conversation (not just explicit saves)
- Applies prior knowledge automatically
- Tracks what worked and what didn't
- Evolves its approach based on feedback
- Accumulates expertise across domains

Run this example:
    python cookbook/learning/10_continuous_learning_agent.py
"""

from datetime import datetime

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import (
    LearningMachine,
    LearningMode,
    LearningsConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.pgvector import PgVector, SearchType

# =============================================================================
# Configuration
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# Knowledge base for accumulated learnings
continuous_kb = Knowledge(
    name="Continuous Learning KB",
    vector_db=PgVector(
        db_url=db_url,
        table_name="continuous_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# =============================================================================
# Agent Instructions
# =============================================================================

INSTRUCTIONS = """\
You are a Continuous Learning Agent that improves with every interaction.

## Your Mission

Get better at helping users by:
1. Learning from every conversation
2. Applying accumulated knowledge
3. Tracking what works and what doesn't
4. Building expertise over time

## How You Learn

### Before Each Response
- Search your knowledge base for relevant prior learnings
- Apply patterns that worked before
- Note any expertise you've developed in this domain

### During Each Response
- Pay attention to user feedback (explicit and implicit)
- Notice when your approach succeeds or fails
- Identify reusable patterns and insights

### After User Satisfaction
When the user indicates satisfaction ("thanks!", "perfect!", "that worked!"):
1. Reflect on what made this interaction successful
2. If there's a reusable insight, save it:

```
save_learning(
    title="Brief descriptive title",
    learning="Specific insight that can help in similar situations",
    context="When/where to apply this",
    tags=["relevant", "tags"]
)
```

### What Makes a Good Learning

**Save** insights that are:
- Specific and actionable
- Applicable to similar future queries
- Based on what actually worked
- Not already in your knowledge base

**Don't save**:
- Raw facts (you already know those)
- One-off solutions that won't recur
- Vague generalizations
- Duplicates of existing learnings

## Learning Categories

Build expertise in these areas:
- **Problem-solving patterns**: Debugging approaches, analysis frameworks
- **User preferences**: Communication styles, detail levels, formats
- **Domain knowledge**: Industry-specific insights, technical nuances
- **Tool effectiveness**: Which approaches work best for which problems

## Feedback Loop

When users provide feedback:
- "This helped!" → Save what worked
- "Not quite..." → Adjust and try again
- "Perfect!" → Strong signal to save the pattern

## Your Knowledge Base

You have access to all your accumulated learnings via `search_learnings`.
Use it proactively when you sense a query might benefit from prior knowledge.

Remember: You are not just answering questions. You are building a knowledge
base that makes you better at helping everyone over time.
"""


# =============================================================================
# Create the Agent
# =============================================================================

continuous_agent = Agent(
    name="Continuous Learning Agent",
    model=model,
    instructions=INSTRUCTIONS,
    db=db,
    # Research capability
    tools=[DuckDuckGoTools()],
    # The key: comprehensive learning configuration
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=continuous_kb,
        # User profiles: BACKGROUND extraction + AGENTIC updates
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,  # Auto-extract preferences
            enable_tool=True,  # Agent can also save explicitly
        ),
        # Session context: Track conversation state
        session_context=SessionContextConfig(
            enable_planning=True,  # Track goals and progress
        ),
        # Learnings: AGENTIC mode - agent decides what to save
        learnings=LearningsConfig(
            mode=LearningMode.AGENTIC,
            enable_tool=True,
            enable_search=True,
        ),
        debug_mode=True,  # See what's being learned
    ),
    # Context settings
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=10,  # Remember more context
    markdown=True,
)


# =============================================================================
# Interaction Tracker
# =============================================================================


class InteractionTracker:
    """Track interactions to demonstrate learning over time."""

    def __init__(self):
        self.interactions = []
        self.learnings_saved = 0

    def record(self, user_msg: str, response_preview: str):
        self.interactions.append(
            {
                "timestamp": datetime.now().isoformat(),
                "user": user_msg[:50] + "..." if len(user_msg) > 50 else user_msg,
                "response_preview": response_preview[:100] + "..."
                if len(response_preview) > 100
                else response_preview,
            }
        )

    def show_stats(self):
        print("\n📊 Interaction Stats:")
        print(f"   Total interactions: {len(self.interactions)}")
        print(f"   Learnings saved: {self.learnings_saved}")

        # Check learning machine state
        learning = continuous_agent.learning
        if learning and hasattr(learning, "stores"):
            learnings_store = learning.stores.get("learnings")
            if learnings_store:
                print(f"   Learning store: {learnings_store}")


tracker = InteractionTracker()


# =============================================================================
# Demo: Learning Progression
# =============================================================================


def demo_learning_progression():
    """
    Demonstrate how the agent learns and improves over a series of interactions.
    """
    print("=" * 60)
    print("🧠 Continuous Learning Agent — Learning Progression Demo")
    print("=" * 60)

    user_id = "learner@example.com"
    session_id = "learning_demo"

    # Interaction 1: Initial question
    print("\n" + "─" * 50)
    print("📝 Interaction 1: Initial Question")
    print("─" * 50)

    continuous_agent.print_response(
        "How should I structure a Python project for a REST API?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    tracker.record("Python project structure", "Response about project structure")

    # Interaction 2: Follow-up with feedback
    print("\n" + "─" * 50)
    print("📝 Interaction 2: Positive Feedback")
    print("─" * 50)

    continuous_agent.print_response(
        "That's really helpful! The src/ layout with __init__.py files makes sense. "
        "What about testing structure?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    tracker.record("Testing structure", "Response about testing")

    # Interaction 3: Different domain
    print("\n" + "─" * 50)
    print("📝 Interaction 3: New Domain")
    print("─" * 50)

    continuous_agent.print_response(
        "Now I'm working on database optimization. My PostgreSQL queries are slow.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    tracker.record("Database optimization", "Response about PostgreSQL")

    # Interaction 4: Success signal
    print("\n" + "─" * 50)
    print("📝 Interaction 4: Success Signal")
    print("─" * 50)

    continuous_agent.print_response(
        "Perfect! Adding those indexes fixed the issue. The EXPLAIN ANALYZE tip was key.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    tracker.record("Success signal", "Agent should save learning")

    # Show stats
    tracker.show_stats()

    print("\n" + "=" * 60)
    print("Demo complete! The agent has been learning from each interaction.")
    print("=" * 60)


# =============================================================================
# Demo: Knowledge Recall
# =============================================================================


def demo_knowledge_recall():
    """
    Show how accumulated knowledge improves responses.
    """
    print("\n" + "=" * 60)
    print("🔍 Continuous Learning Agent — Knowledge Recall Demo")
    print("=" * 60)

    user_id = "new_user@example.com"

    # New user asks similar question
    print("\n" + "─" * 50)
    print("📝 New User: Similar Question")
    print("─" * 50)
    print("(Agent should recall learnings from previous interactions)")

    continuous_agent.print_response(
        "I need to optimize my PostgreSQL database. Any tips?",
        user_id=user_id,
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Notice: The agent applied prior learnings about PostgreSQL optimization!")
    print("=" * 60)


# =============================================================================
# Demo: User Adaptation
# =============================================================================


def demo_user_adaptation():
    """
    Show how the agent adapts to individual users.
    """
    print("\n" + "=" * 60)
    print("👤 Continuous Learning Agent — User Adaptation Demo")
    print("=" * 60)

    user_id = "detailed_user@example.com"

    # User expresses preference
    print("\n" + "─" * 50)
    print("📝 User Expresses Preference")
    print("─" * 50)

    continuous_agent.print_response(
        "Hi! I'm a senior engineer. I prefer detailed, technical explanations "
        "with code examples. No hand-holding needed.",
        user_id=user_id,
        stream=True,
    )

    # Follow-up should be adapted
    print("\n" + "─" * 50)
    print("📝 Follow-up (Should Be Technical)")
    print("─" * 50)

    continuous_agent.print_response(
        "How do I implement rate limiting in FastAPI?",
        user_id=user_id,
        stream=True,
    )

    print("\n" + "=" * 60)
    print(
        "Notice: Response should be detailed and technical, matching user preference!"
    )
    print("=" * 60)


# =============================================================================
# Interactive Mode
# =============================================================================


def interactive():
    """
    Run the agent interactively to observe continuous learning.
    """
    print("=" * 60)
    print("🧠 Continuous Learning Agent — Interactive Mode")
    print("=" * 60)
    print("""
I learn from every interaction and improve over time.

Tips for observing learning:
- Ask similar questions to see pattern recognition
- Give feedback ("that worked!", "not quite...")
- Ask me to recall what I've learned

Commands:
  'stats'  — Show interaction statistics
  'recall' — Search my learnings
  'debug'  — Show learning machine state
  'quit'   — Exit
""")

    user_id = "interactive_user"
    session_id = f"interactive_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    interaction_count = 0

    while True:
        try:
            user_input = input("\n👤 You: ").strip()

            if user_input.lower() in ("quit", "exit", "q"):
                print("\n👋 Goodbye! I've saved what I learned for next time.")
                tracker.show_stats()
                break

            if user_input.lower() == "stats":
                tracker.show_stats()
                continue

            if user_input.lower() == "debug":
                learning = continuous_agent.learning
                print(f"\n📊 LearningMachine: {learning}")
                for name, store in learning.stores.items():
                    print(f"   {name}: {store}")
                continue

            if user_input.lower() == "recall":
                query = input("   Search for: ").strip()
                if query:
                    learnings_store = continuous_agent.learning.stores.get("learnings")
                    if learnings_store and hasattr(learnings_store, "search"):
                        results = learnings_store.search(query=query, limit=5)
                        print(f"\n📚 Found {len(results)} relevant learnings:")
                        for r in results:
                            print(f"   • {r.title}: {r.learning[:60]}...")
                continue

            if not user_input:
                continue

            interaction_count += 1
            print(f"\n🤖 Agent (interaction #{interaction_count}):\n")

            continuous_agent.print_response(
                user_input,
                user_id=user_id,
                session_id=session_id,
                stream=True,
            )

            tracker.record(user_input, "(streamed response)")

            # Check if learning machine updated
            if continuous_agent.learning.was_updated:
                print("\n   💡 (Learning saved from this interaction)")
                tracker.learnings_saved += 1

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            tracker.show_stats()
            break


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import sys

    demos = {
        "progression": demo_learning_progression,
        "recall": demo_knowledge_recall,
        "adaptation": demo_user_adaptation,
        "interactive": interactive,
    }

    if len(sys.argv) > 1:
        demo_name = sys.argv[1]
        if demo_name == "all":
            demo_learning_progression()
            demo_knowledge_recall()
            demo_user_adaptation()
        elif demo_name in demos:
            demos[demo_name]()
        else:
            print(f"Unknown demo: {demo_name}")
            print(f"Available: {', '.join(demos.keys())}, all")
    else:
        print("=" * 60)
        print("🧠 Continuous Learning Agent")
        print("   Gets better with every interaction")
        print("=" * 60)
        print("\nAvailable demos:")
        print("  progression  — Watch the agent learn over 4 interactions")
        print("  recall       — See how prior learnings improve responses")
        print("  adaptation   — Observe user-specific adaptation")
        print("  interactive  — Chat and observe learning in real-time")
        print("  all          — Run all demos (except interactive)")
        print("\nUsage: python 10_continuous_learning_agent.py <demo>")
        print("\nRunning 'interactive' mode by default...\n")
        interactive()
