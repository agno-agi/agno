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
    # Alice logs a meeting
    print("\n" + "=" * 60)
    print("PHASE 1: Alice Logs Meeting")
    print("=" * 60 + "\n")

    alice_intro = create_sales_agent("alice@sales.com", "alice-session-1")
    alice_intro.print_response(
        "I'm Alice, West Coast AE focusing on tech companies.",
        stream=True,
    )

    alice_meeting_bob = create_sales_agent("alice@sales.com", "alice-session-1")
    alice_meeting_bob.print_response(
        "I just had a meeting TODAY with Bob Chen, the CTO at Acme Corp. "
        "Bob Chen prefers async communication via Slack.",
        stream=True,
    )

    alice_acme_details = create_sales_agent("alice@sales.com", "alice-session-1")
    alice_acme_details.print_response(
        "Acme Corp is a Series B dev tools startup, 200 employees, uses PostgreSQL. "
        "Bob works at Acme. We discussed their Enterprise plan.",
        stream=True,
    )
    alice_acme_details.get_learning_machine().session_context_store.print(
        session_id="alice-session-1"
    )

    # Carlos queries shared CRM data
    print("\n" + "=" * 60)
    print("PHASE 2: Carlos Queries CRM")
    print("=" * 60 + "\n")

    carlos_query_acme = create_sales_agent("carlos@sales.com", "carlos-session-1")
    carlos_query_acme.print_response(
        "Carlos here, East Coast SDR. What do we know about Acme Corp and Bob Chen?",
        stream=True,
    )

    # Alice closes deal
    print("\n" + "=" * 60)
    print("PHASE 3: Alice Closes Deal")
    print("=" * 60 + "\n")

    alice_close_announcement = create_sales_agent("alice@sales.com", "alice-session-2")
    alice_close_announcement.print_response(
        "Great news! I closed Acme Corp for $55K ACV today!",
        stream=True,
    )

    alice_win_factors = create_sales_agent("alice@sales.com", "alice-session-2")
    alice_win_factors.print_response(
        "Key win factors: PostgreSQL integration matched their stack, "
        "async communication style fit their culture, "
        "and we moved fast on their Q1 timeline. Bob championed internally.",
        stream=True,
    )
    alice_win_factors.get_learning_machine().learned_knowledge_store.print(
        query="sales"
    )
    alice_win_factors.get_learning_machine().session_context_store.print(
        session_id="alice-session-2"
    )

    # Cross-user sharing verification
    print("\n" + "=" * 60)
    print("Cross-user sharing: Alice created -> Carlos queried -> Alice closed")
    print("=" * 60)
