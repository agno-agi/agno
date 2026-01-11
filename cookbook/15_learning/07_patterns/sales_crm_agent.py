"""
Pattern: Sales CRM Agent with Entity Memory
============================================
A sales assistant that tracks people, companies, deals, and relationships.

This cookbook demonstrates:
1. EntityMemory AGENTIC mode - Agent calls tools to manage entities
2. Entity creation with create_entity
3. Facts, events, relationships via add_fact, add_event, add_relationship
4. Cross-user entity sharing - All sales reps see the same account data
5. LearnedKnowledge AGENTIC mode - Agent saves sales patterns via tools

Scenario:
- Alice logs a meeting and CREATES entities (Bob, Acme) with facts/events
- Carlos (different rep) queries the shared entity data
- Alice closes deal, adds event to entity, saves winning pattern

Expected tool calls (on fresh DB):
- Phase 1: search_entities -> create_entity -> add_fact -> add_event -> add_relationship
- Phase 2: search_entities (finds Alice's data)
- Phase 3: search_entities -> add_event -> save_learning (deal close + pattern)
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
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Shared knowledge base for sales patterns
sales_kb = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="sales_patterns_kb",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


def create_sales_agent(rep_id: str, session_id: str) -> Agent:
    """Create a sales CRM agent for a sales rep."""
    return Agent(
        model=OpenAIResponses(id="gpt-4o"),
        db=db,
        instructions="""\
You are a sales CRM assistant that tracks entities (people, companies).

CRITICAL: You MUST use these tools to store information:

1. ALWAYS search first: search_entities(query, entity_type, limit)
2. If NOT found, CREATE the entity: create_entity(entity_id, entity_type, name, description)
3. THEN add data to the entity:
   - add_fact(entity_id, entity_type, fact) - for timeless info like "CTO at Acme"
   - add_event(entity_id, entity_type, event, date) - for time-bound events like meetings
   - add_relationship(entity_id, entity_type, target_entity_id, relation) - for connections

Entity ID format: lowercase with underscores (e.g., "bob_chen", "acme_corp")
Entity types: "person", "company"

IMPORTANT:
- You MUST call create_entity before adding facts/events to a new entity
- You MUST call add_event to record meetings, deals, and other occurrences
- You MUST call add_relationship to link people to companies

Be thorough - capture all the information provided.

When a deal closes successfully, use save_learning to record the winning pattern
so other sales reps can learn from it.""",
        learning=LearningMachine(
            knowledge=sales_kb,
            # UserProfile disabled - ALWAYS mode confuses entities (Bob, Acme)
            # with user profile (Alice) during extraction
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,
                namespace="sales:global",
                enable_agent_tools=True,
            ),
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,  # Changed from ALWAYS to avoid extraction confusion
                namespace="sales:patterns",
            ),
        ),
        user_id=rep_id,
        session_id=session_id,
        markdown=True,
    )


# ============================================================================
# Demo: Sales CRM Scenario
# ============================================================================

if __name__ == "__main__":
    # =========================================================================
    # PHASE 1: Alice logs a meeting and creates entities
    # =========================================================================
    print("=" * 70)
    print("PHASE 1: Alice Logs Meeting - Entity Creation")
    print("=" * 70)
    print(
        "\nExpected: search_entities -> create_entity -> add_fact -> add_event -> add_relationship\n"
    )

    alice = create_sales_agent("alice@sales.com", "alice-session-1")

    print("--- Alice logs meeting ---\n")
    alice.print_response(
        "I'm Alice, West Coast AE focusing on tech companies. "
        "I just had a meeting TODAY with Bob Chen, the CTO at Acme Corp. "
        "Please create entities for both Bob and Acme and record this information:\n"
        "- Bob Chen: CTO, prefers async communication via Slack\n"
        "- Acme Corp: Series B dev tools startup, 200 employees, uses PostgreSQL\n"
        "- Bob works at Acme (add this relationship)\n"
        "- Record today's meeting as an event on Acme: discussed Enterprise plan",
        stream=True,
    )

    # =========================================================================
    # PHASE 2: Carlos (different rep) queries shared data
    # =========================================================================
    print("\n" + "=" * 70)
    print("PHASE 2: Carlos Queries Shared CRM Data")
    print("=" * 70)
    print("\nExpected: search_entities finds Alice's entities\n")

    carlos = create_sales_agent("carlos@sales.com", "carlos-session-1")

    print("--- Carlos queries Acme ---\n")
    carlos.print_response(
        "Carlos here, East Coast SDR. Search for what we know about Acme Corp and Bob Chen.",
        stream=True,
    )

    # =========================================================================
    # PHASE 3: Alice closes deal - adds event, saves winning pattern
    # =========================================================================
    print("\n" + "=" * 70)
    print("PHASE 3: Alice Closes Deal - Add Event + Save Winning Pattern")
    print("=" * 70)
    print(
        "\nExpected: add_event to record deal close, save_learning to capture pattern\n"
    )

    alice2 = create_sales_agent("alice@sales.com", "alice-session-2")

    print("--- Alice closes the deal ---\n")
    alice2.print_response(
        "Great news! I closed Acme Corp for $55K ACV today! "
        "Please add this as an EVENT to the Acme Corp entity with today's date. "
        "Also, save a LEARNING about why this deal succeeded so other reps can benefit. "
        "Key win factors: PostgreSQL integration matched their stack, "
        "async communication style fit their culture, "
        "and we moved fast on their Q1 timeline. Bob championed internally.",
        stream=True,
    )

    print("\n--- Learned Pattern (saved via save_learning tool) ---")
    alice2.get_learning_machine().learned_knowledge_store.print(query="sales win")

    # =========================================================================
    # Evidence Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("EVIDENCE SUMMARY")
    print("=" * 70)

    print("\n[1] LEARNED KNOWLEDGE (saved via save_learning):")
    alice2.get_learning_machine().learned_knowledge_store.print(query="sales")

    print("\n[2] ENTITY MEMORY - Verify entities were created:")
    em = alice2.get_learning_machine().entity_memory_store
    if em:
        print("\n    Searching for Acme Corp...")
        results = em.search(
            query="Acme Corp", entity_type="company", limit=1, namespace="sales:global"
        )
        if results:
            print(
                f"    Found: {results[0].name if hasattr(results[0], 'name') else results[0]}"
            )
        else:
            print("    NOT FOUND - Entity creation failed!")

        print("\n    Searching for Bob Chen...")
        results = em.search(
            query="Bob Chen", entity_type="person", limit=1, namespace="sales:global"
        )
        if results:
            print(
                f"    Found: {results[0].name if hasattr(results[0], 'name') else results[0]}"
            )
        else:
            print("    NOT FOUND - Entity creation failed!")

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
    print("""
Review the tool calls above to verify:
- Phase 1: create_entity, add_fact, add_event, add_relationship were called
- Phase 2: search_entities found the entities (cross-user sharing)
- Phase 3: add_event recorded the deal close
""")
