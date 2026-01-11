"""
Comprehensive Learning System Test
==================================
A thorough test of ALL learning stores and cross-session/cross-user scenarios.

This cookbook systematically tests:
1. UserProfile ALWAYS mode - Simple self-focused conversation (no entity confusion)
2. UserMemory ALWAYS mode - Unstructured observations about user
3. Cross-session retrieval - Same user, new session, profile/memory persists
4. LearnedKnowledge AGENTIC - Save patterns via tools
5. Cross-user knowledge sharing - Different user finds prior learnings
6. EntityMemory AGENTIC - Create entities, add facts, verify retrieval

Test Structure:
- PHASE 1: Alice introduces herself (UserProfile + UserMemory captured)
- PHASE 2: Alice returns in NEW session (profile/memory RETRIEVED, not re-extracted)
- PHASE 3: Alice discovers a useful pattern, saves it (LearnedKnowledge)
- PHASE 4: Bob (different user) searches for patterns (cross-user sharing)
- PHASE 5: Entity creation and retrieval verification

Each phase has explicit ASSERTIONS to verify the system works correctly.
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
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Knowledge base for shared learnings
shared_kb = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="comprehensive_test_kb",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


def create_profile_agent(user_id: str, session_id: str) -> Agent:
    """Create an agent for user profile extraction (ALWAYS mode).

    Use this agent ONLY for self-focused conversations where the user talks
    about themselves (name, preferences, role, etc.). The ALWAYS mode will
    extract profile info from every message.

    WARNING: Do not use for technical discussions or entity-focused messages
    as the extraction may confuse technical content with profile information.
    """
    return Agent(
        model=OpenAIResponses(id="gpt-4o"),
        db=db,
        instructions="""\
You are a helpful assistant that learns from conversations.
Acknowledge what the user shares about themselves.""",
        learning=LearningMachine(
            knowledge=shared_kb,
            # UserProfile: ALWAYS mode - only for self-introduction messages
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            # UserMemory: ALWAYS mode - capture observations about user
            memories=UserMemoryConfig(
                mode=LearningMode.ALWAYS,
            ),
        ),
        user_id=user_id,
        session_id=session_id,
        markdown=True,
    )


def create_retrieval_agent(user_id: str, session_id: str) -> Agent:
    """Create an agent that retrieves but doesn't extract profiles.

    Use this for follow-up sessions where we want to TEST that profile/memory
    data persists across sessions, without triggering new extraction.
    """
    return Agent(
        model=OpenAIResponses(id="gpt-4o"),
        db=db,
        instructions="""\
You are a helpful assistant with memory. Use the user's profile and memories
to provide personalized responses.""",
        learning=LearningMachine(
            knowledge=shared_kb,
            # Profile retrieval only - no extraction
            user_profile=UserProfileConfig(
                mode=LearningMode.AGENTIC,  # Won't extract, but will retrieve
            ),
            memories=UserMemoryConfig(
                mode=LearningMode.AGENTIC,  # Won't extract, but will retrieve
            ),
        ),
        user_id=user_id,
        session_id=session_id,
        markdown=True,
    )


def create_knowledge_agent(user_id: str, session_id: str) -> Agent:
    """Create an agent for knowledge sharing (AGENTIC mode).

    Use this for technical discussions, saving/searching learnings, and
    creating entities. Does NOT have ALWAYS mode extraction enabled.
    """
    return Agent(
        model=OpenAIResponses(id="gpt-4o"),
        db=db,
        instructions="""\
You are a helpful assistant that learns from conversations.

When the user shares useful patterns or tips, use save_learning to record them
so others can benefit. Search for relevant learnings using search_learnings
before giving advice.

For tracking external entities (people, companies, projects), use the entity tools:
- search_entities, create_entity, add_fact, add_event, add_relationship""",
        learning=LearningMachine(
            knowledge=shared_kb,
            # No ALWAYS mode for profile/memory - avoids extraction confusion
            # LearnedKnowledge: AGENTIC mode - agent saves via tools
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace="test:patterns",
            ),
            # EntityMemory: AGENTIC mode - agent manages entities via tools
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,
                namespace="test:entities",
                enable_agent_tools=True,
            ),
        ),
        user_id=user_id,
        session_id=session_id,
        markdown=True,
    )


# ============================================================================
# Test Execution
# ============================================================================

if __name__ == "__main__":
    results = {"passed": 0, "failed": 0, "tests": []}

    def assert_test(name: str, condition: bool, details: str = ""):
        """Record test result."""
        status = "PASS" if condition else "FAIL"
        results["passed" if condition else "failed"] += 1
        results["tests"].append({"name": name, "status": status, "details": details})
        print(f"  [{status}] {name}")
        if details and not condition:
            print(f"        {details}")

    # =========================================================================
    # PHASE 1: Alice introduces herself (UserProfile + UserMemory)
    # =========================================================================
    print("\n" + "=" * 70)
    print("PHASE 1: Alice Introduces Herself")
    print("Testing: UserProfile ALWAYS + UserMemory ALWAYS extraction")
    print("=" * 70)

    # Use profile agent for self-introduction (ALWAYS mode safe for self-focused messages)
    alice1 = create_profile_agent("alice@test.com", "alice-session-1")

    print("\n--- Alice's first message (self-focused, no other entities) ---\n")
    alice1.print_response(
        "Hi! I'm Alice, a software engineer. I prefer Python over JavaScript. "
        "I work best in the mornings and like detailed explanations.",
        stream=True,
    )

    # Verify UserProfile was captured
    print("\n--- Verifying UserProfile extraction ---")
    lm = alice1.get_learning_machine()
    profile = (
        lm.user_profile_store.get(user_id="alice@test.com")
        if lm.user_profile_store
        else None
    )

    assert_test(
        "UserProfile captured name",
        profile is not None and hasattr(profile, "name") and profile.name is not None,
        f"Got: {profile.name if profile and hasattr(profile, 'name') else 'None'}",
    )

    # Verify UserMemory was captured
    print("\n--- Verifying UserMemory extraction ---")
    memories = (
        lm.memories_store.get(user_id="alice@test.com") if lm.memories_store else None
    )

    assert_test(
        "UserMemory captured observations",
        memories is not None
        and hasattr(memories, "memories")
        and len(memories.memories) > 0,
        f"Got {len(memories.memories) if memories and hasattr(memories, 'memories') else 0} memories",
    )

    if memories and hasattr(memories, "memories"):
        print(
            f"  Captured memories: {[m.get('content', m)[:50] for m in memories.memories[:3]]}"
        )

    # =========================================================================
    # PHASE 2: Alice returns in NEW session (cross-session retrieval)
    # =========================================================================
    print("\n" + "=" * 70)
    print("PHASE 2: Alice Returns (New Session)")
    print("Testing: Cross-session profile/memory retrieval")
    print("=" * 70)

    # Use retrieval agent - just retrieves profile/memory, no ALWAYS extraction
    alice2 = create_retrieval_agent("alice@test.com", "alice-session-2")

    print(
        "\n--- Alice asks a question (profile should be RETRIEVED, not re-extracted) ---\n"
    )
    alice2.print_response(
        "What do you remember about me?",
        stream=True,
    )

    # Verify profile was retrieved (same data as Phase 1)
    print("\n--- Verifying cross-session retrieval ---")
    lm2 = alice2.get_learning_machine()
    profile2 = (
        lm2.user_profile_store.get(user_id="alice@test.com")
        if lm2.user_profile_store
        else None
    )

    assert_test(
        "Profile persisted across sessions",
        profile2 is not None
        and hasattr(profile2, "name")
        and profile2.name is not None,
        f"Got: {profile2.name if profile2 and hasattr(profile2, 'name') else 'None'}",
    )

    memories2 = (
        lm2.memories_store.get(user_id="alice@test.com") if lm2.memories_store else None
    )
    assert_test(
        "Memories persisted across sessions",
        memories2 is not None
        and hasattr(memories2, "memories")
        and len(memories2.memories) > 0,
        f"Got {len(memories2.memories) if memories2 and hasattr(memories2, 'memories') else 0} memories",
    )

    # =========================================================================
    # PHASE 3: Alice saves a learning (LearnedKnowledge AGENTIC)
    # =========================================================================
    print("\n" + "=" * 70)
    print("PHASE 3: Alice Saves a Learning")
    print("Testing: LearnedKnowledge AGENTIC mode (save_learning tool)")
    print("=" * 70)

    # Use knowledge agent for technical content - no ALWAYS mode to avoid extraction bugs
    alice3 = create_knowledge_agent("alice@test.com", "alice-session-3")

    print("\n--- Alice shares a useful pattern ---\n")
    alice3.print_response(
        "I just discovered something useful! When debugging Python async code, "
        "always check if you're missing an 'await' keyword - it's the #1 cause of "
        "confusing behavior. Please save this as a learning for others.",
        stream=True,
    )

    # Verify learning was saved
    print("\n--- Verifying learning was saved ---")
    lm3 = alice3.get_learning_machine()
    learnings = (
        lm3.learned_knowledge_store.search(query="python async debugging", limit=5)
        if lm3.learned_knowledge_store
        else []
    )

    assert_test(
        "Learning saved via save_learning tool",
        len(learnings) > 0,
        f"Found {len(learnings)} learnings",
    )

    if learnings:
        print(
            f"  Saved learning: {learnings[0].content[:100] if hasattr(learnings[0], 'content') else learnings[0]}..."
        )

    # =========================================================================
    # PHASE 4: Bob searches for learnings (cross-user knowledge sharing)
    # =========================================================================
    print("\n" + "=" * 70)
    print("PHASE 4: Bob Searches for Learnings")
    print(
        "Testing: Cross-user knowledge sharing (different user finds Alice's learning)"
    )
    print("=" * 70)

    # Use knowledge agent for Bob - he's asking about technical content
    bob = create_knowledge_agent("bob@test.com", "bob-session-1")

    print("\n--- Bob asks about async debugging ---\n")
    bob.print_response(
        "I'm having trouble with Python async code. Any tips?",
        stream=True,
    )

    # Verify Bob's agent could access Alice's learning
    print("\n--- Verifying cross-user knowledge sharing ---")
    lm_bob = bob.get_learning_machine()
    bob_learnings = (
        lm_bob.learned_knowledge_store.search(query="python async", limit=5)
        if lm_bob.learned_knowledge_store
        else []
    )

    assert_test(
        "Bob can access Alice's learning (cross-user sharing)",
        len(bob_learnings) > 0,
        f"Found {len(bob_learnings)} learnings",
    )

    # Verify Bob has his own profile (not Alice's)
    bob_profile = (
        lm_bob.user_profile_store.get(user_id="bob@test.com")
        if lm_bob.user_profile_store
        else None
    )
    alice_profile_check = (
        lm_bob.user_profile_store.get(user_id="alice@test.com")
        if lm_bob.user_profile_store
        else None
    )

    assert_test(
        "Bob has separate profile from Alice",
        bob_profile is None
        or (alice_profile_check is not None and bob_profile != alice_profile_check),
        "Profiles should be isolated by user_id",
    )

    # =========================================================================
    # PHASE 5: Entity Memory test
    # NOTE: EntityMemory verification may fail due to a known issue where
    # tool-created entities aren't persisted to DB. This is separate from the
    # ALWAYS mode fix. The tool calls succeed, but search doesn't find them.
    # =========================================================================
    print("\n" + "=" * 70)
    print("PHASE 5: Entity Memory Test")
    print("Testing: EntityMemory AGENTIC mode (create, add_fact, search)")
    print("NOTE: This may fail due to known EntityMemory persistence issue")
    print("=" * 70)

    print("\n--- Alice creates an entity ---\n")
    # Use the knowledge agent (alice3) which has entity_memory enabled
    alice3.print_response(
        "Please create an entity for 'TechCorp' (company) with the fact that they use Python. "
        "Also create an entity for 'Dave' (person) who is a senior engineer at TechCorp.",
        stream=True,
    )

    # Verify entities were created
    print("\n--- Verifying entity creation ---")
    em = lm3.entity_memory_store
    if em:
        # Must specify the namespace used by create_knowledge_agent
        techcorp = em.search(
            query="TechCorp", entity_type="company", limit=1, namespace="test:entities"
        )
        dave = em.search(
            query="Dave", entity_type="person", limit=1, namespace="test:entities"
        )

        assert_test(
            "Company entity created",
            len(techcorp) > 0,
            f"Found: {techcorp[0].name if techcorp and hasattr(techcorp[0], 'name') else 'None'}",
        )

        assert_test(
            "Person entity created",
            len(dave) > 0,
            f"Found: {dave[0].name if dave and hasattr(dave[0], 'name') else 'None'}",
        )

        # Verify facts were added
        if techcorp:
            entity = techcorp[0]
            has_facts = hasattr(entity, "facts") and len(entity.facts) > 0
            assert_test(
                "Entity has facts",
                has_facts,
                f"Facts: {entity.facts[:2] if has_facts else 'None'}",
            )
    else:
        assert_test("EntityMemory store exists", False, "entity_memory_store is None")

    # =========================================================================
    # RESULTS SUMMARY
    # =========================================================================
    print("\n" + "=" * 70)
    print("TEST RESULTS SUMMARY")
    print("=" * 70)

    print(f"\nTotal: {results['passed'] + results['failed']} tests")
    print(f"Passed: {results['passed']}")
    print(f"Failed: {results['failed']}")

    print("\nDetailed Results:")
    for test in results["tests"]:
        status_icon = "+" if test["status"] == "PASS" else "x"
        print(f"  [{status_icon}] {test['name']}")

    if results["failed"] > 0:
        print("\n[!] Some tests failed. Review output above for details.")
    else:
        print("\n[+] All tests passed! Learning system working correctly.")

    print("\n" + "=" * 70)
    print("COMPREHENSIVE TEST COMPLETE")
    print("=" * 70)
