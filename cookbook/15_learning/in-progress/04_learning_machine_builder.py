"""
Combined: LearningMachine Builder Pattern
=========================================
Three levels of configuration complexity.

LearningMachine supports three DX levels:

**Level 1: Dead Simple**
    learning=True  # Just works

**Level 2: Pick What You Want**
    learning=LearningMachine(
        user_profile=True,
        session_context=True,
    )

**Level 3: Full Control**
    learning=LearningMachine(
        user_profile=UserProfileConfig(...),
        session_context=SessionContextConfig(...),
    )

This cookbook shows all three levels.

Run:
    python cookbook/15_learning/combined/04_learning_machine_builder.py
"""

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
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")


# ============================================================================
# Level 1: Dead Simple
# ============================================================================
def demo_level_1():
    """The simplest possible learning agent."""
    print("=" * 60)
    print("Level 1: Dead Simple")
    print("=" * 60)

    print("\n--- Code ---")
    print("""
    agent = Agent(
        model=model,
        db=db,
        learning=True,  # That's it!
    )
    """)

    # Create the agent
    agent = Agent(
        name="Simple Agent",
        model=model,
        db=db,
        learning=True,  # Enables user_profile in BACKGROUND mode
        markdown=True,
    )

    print("\n--- Demo ---\n")
    agent.print_response(
        "Hi, I'm Alex and I love Python. Remember that!",
        user_id="level1@example.com",
        session_id="simple_1",
        stream=True,
    )

    print("\n--- Later ---\n")
    agent.print_response(
        "What programming language should you recommend to me?",
        user_id="level1@example.com",
        session_id="simple_2",
        stream=True,
    )

    print("\n✅ Level 1: Single boolean, sensible defaults")


# ============================================================================
# Level 2: Pick What You Want
# ============================================================================
def demo_level_2():
    """Selectively enable stores with defaults."""
    print("\n" + "=" * 60)
    print("Level 2: Pick What You Want")
    print("=" * 60)

    print("\n--- Code ---")
    print("""
    agent = Agent(
        model=model,
        db=db,
        learning=LearningMachine(
            db=db,
            model=model,
            user_profile=True,      # Enable with defaults
            session_context=True,   # Enable with defaults
            entity_memory=False,    # Explicitly disable
            # learned_knowledge omitted = disabled
        ),
    )
    """)

    # Create the agent
    agent = Agent(
        name="Selective Agent",
        model=model,
        db=db,
        learning=LearningMachine(
            db=db,
            model=model,
            user_profile=True,
            session_context=True,
            entity_memory=False,
        ),
        markdown=True,
    )

    print("\n--- Demo ---\n")
    agent.print_response(
        "I'm working on a complex migration project. "
        "First, I need to understand the current architecture.",
        user_id="level2@example.com",
        session_id="selective_1",
        stream=True,
    )

    print("\n--- Continue ---\n")
    agent.print_response(
        "What are we working on?",
        user_id="level2@example.com",
        session_id="selective_1",
        stream=True,
    )

    print("\n✅ Level 2: Boolean flags for each store")


# ============================================================================
# Level 3: Full Control
# ============================================================================
def demo_level_3():
    """Detailed configuration for each store."""
    print("\n" + "=" * 60)
    print("Level 3: Full Control")
    print("=" * 60)

    print("\n--- Code ---")
    print("""
    agent = Agent(
        model=model,
        db=db,
        learning=LearningMachine(
            db=db,
            model=model,
            knowledge=knowledge,  # For learned_knowledge
            user_profile=UserProfileConfig(
                mode=LearningMode.AGENTIC,
                enable_agent_tools=True,
                agent_can_update_memories=True,
            ),
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.PROPOSE,
                namespace="engineering",
                enable_agent_tools=True,
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,
                namespace="engineering",
                enable_agent_tools=True,
                agent_can_create_entity=True,
            ),
        ),
    )
    """)

    # Create knowledge base
    knowledge = Knowledge(
        vector_db=PgVector(
            db_url=db_url,
            table_name="level3_learnings",
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )

    # Create the agent
    agent = Agent(
        name="Full Control Agent",
        model=model,
        db=db,
        instructions="""\
You are a fully configured learning agent.

Your capabilities:
- AGENTIC user profile: You decide when to remember things about users
- Session planning: You track goals and progress
- PROPOSE learnings: You suggest learnings for user approval
- AGENTIC entities: You track external entities

Be explicit when using these capabilities.
""",
        learning=LearningMachine(
            db=db,
            model=model,
            knowledge=knowledge,
            user_profile=UserProfileConfig(
                mode=LearningMode.AGENTIC,
                enable_agent_tools=True,
            ),
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.PROPOSE,
                namespace="engineering",
                enable_agent_tools=True,
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,
                namespace="engineering",
                enable_agent_tools=True,
            ),
        ),
        markdown=True,
    )

    print("\n--- Demo ---\n")
    agent.print_response(
        "I'm Jordan, a senior engineer. I discovered that using connection "
        "pooling reduces latency by 10x. Track this insight and remember me.",
        user_id="level3@example.com",
        session_id="full_control_1",
        stream=True,
    )

    print("\n✅ Level 3: Config classes for full customization")


# ============================================================================
# Summary: When to Use Each Level
# ============================================================================
def show_summary():
    """Show when to use each level."""
    print("\n" + "=" * 60)
    print("Summary: When to Use Each Level")
    print("=" * 60)

    print("""
┌─────────────────────────────────────────────────────────────┐
│ LEVEL 1: Dead Simple                                        │
│ learning=True                                               │
├─────────────────────────────────────────────────────────────┤
│ Use when:                                                   │
│ • Just getting started                                      │
│ • Only need basic user memory                               │
│ • Prototyping                                               │
│                                                             │
│ Gets you:                                                   │
│ • User profile in BACKGROUND mode                           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ LEVEL 2: Pick What You Want                                 │
│ LearningMachine(user_profile=True, session_context=True)    │
├─────────────────────────────────────────────────────────────┤
│ Use when:                                                   │
│ • You need specific stores                                  │
│ • Default configs are fine                                  │
│ • Want explicit control over what's enabled                 │
│                                                             │
│ Gets you:                                                   │
│ • Selective store enablement                                │
│ • Default modes and settings                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ LEVEL 3: Full Control                                       │
│ LearningMachine(user_profile=UserProfileConfig(...), ...)   │
├─────────────────────────────────────────────────────────────┤
│ Use when:                                                   │
│ • Need specific modes (AGENTIC, PROPOSE, etc.)              │
│ • Custom namespaces for sharing                             │
│ • Fine-grained tool control                                 │
│ • Production deployments                                    │
│                                                             │
│ Gets you:                                                   │
│ • Complete configuration                                    │
│ • Mode control per store                                    │
│ • Namespace scoping                                         │
│ • Tool enablement flags                                     │
└─────────────────────────────────────────────────────────────┘
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_level_1()
    demo_level_2()
    demo_level_3()
    show_summary()

    print("\n" + "=" * 60)
    print("✅ Three DX levels for progressive complexity")
    print("   Level 1: learning=True")
    print("   Level 2: LearningMachine(store=True)")
    print("   Level 3: LearningMachine(store=StoreConfig(...))")
    print("=" * 60)
