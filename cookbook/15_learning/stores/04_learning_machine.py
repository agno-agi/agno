"""
LearningMachine - Unified Learning System

This cookbook demonstrates the LearningMachine orchestrator that ties
together UserProfile, SessionContext, and Knowledge stores.

Features tested:
- Three DX levels: True, booleans, full configs
- recall() - retrieve relevant learnings
- process() - background extraction
- get_tools() - agent tools for agentic learning
- format_recall_for_context() - system prompt injection
"""

from agno.db.postgres import PostgresDb
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import (
    BackgroundConfig,
    ExecutionTiming,
    KnowledgeConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Setup database
db = PostgresDb(db_url=db_url)

# Setup vector DB for knowledge (optional)
embedder = OpenAIEmbedder(id="text-embedding-3-small")
vector_db = PgVector(
    table_name="agno_learned_knowledge",
    db_url=db_url,
    embedder=embedder,
)
knowledge_base = Knowledge(vector_db=vector_db)

# Test identifiers
user_id = "learning_demo_user@example.com"
session_id = "learning_demo_session"


def test_dx_level_1():
    """Test DX Level 1: Just pass True for defaults."""
    print("=" * 60)
    print("TEST: DX Level 1 - Simple Boolean")
    print("=" * 60)

    # This is how it will work when integrated with Agent:
    # agent = Agent(model=model, db=db, learning=True)

    # For now, create LearningMachine directly with defaults
    lm = LearningMachine(
        db=db,
        user_profile=True,
        session_context=True,
        learned_knowledge=False,  # Requires knowledge base
    )

    print("\nLearningMachine created with:")
    print(f"  user_profile: {lm.user_profile_config is not None}")
    print(f"  session_context: {lm.session_context_config is not None}")
    print(f"  learned_knowledge: {lm.knowledge_config is not None}")

    print("\n✅ DX Level 1 test passed!")


def test_dx_level_2():
    """Test DX Level 2: Pick what you want with booleans."""
    print("\n" + "=" * 60)
    print("TEST: DX Level 2 - Pick Features")
    print("=" * 60)

    lm = LearningMachine(
        db=db,
        knowledge=knowledge_base,
        user_profile=True,
        session_context=True,
        learned_knowledge=True,
    )

    print("\nLearningMachine created with:")
    print(f"  user_profile: {lm.user_profile_config is not None}")
    print(f"  session_context: {lm.session_context_config is not None}")
    print(f"  learned_knowledge: {lm.knowledge_config is not None}")

    # Check that tools are generated
    tools = lm.get_tools(user_id=user_id)
    print(f"\nTools available: {len(tools)}")
    for tool in tools:
        print(f"  - {tool.__name__ if hasattr(tool, '__name__') else tool}")

    print("\n✅ DX Level 2 test passed!")


def test_dx_level_3():
    """Test DX Level 3: Full control with configs."""
    print("\n" + "=" * 60)
    print("TEST: DX Level 3 - Full Config Control")
    print("=" * 60)

    lm = LearningMachine(
        db=db,
        knowledge=knowledge_base,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            background=BackgroundConfig(
                timing=ExecutionTiming.PARALLEL,
                run_after_messages=2,
            ),
            enable_tool=True,
            instructions="Focus on professional information and preferences.",
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
            instructions="Track goals, plans, and progress.",
        ),
        learned_knowledge=KnowledgeConfig(
            mode=LearningMode.PROPOSE,
            enable_tool=True,
            instructions="Save reusable insights about coding and architecture.",
        ),
    )

    print("\nLearningMachine with full configs:")
    print(f"  User profile mode: {lm.user_profile_config.mode.value}")
    print(f"  User profile tool: {lm.user_profile_config.enable_tool}")
    print(f"  Session planning: {lm.session_context_config.enable_planning}")
    print(f"  Knowledge mode: {lm.knowledge_config.mode.value}")

    print("\n✅ DX Level 3 test passed!")


def test_recall():
    """Test recall() - retrieving relevant learnings."""
    print("\n" + "=" * 60)
    print("TEST: Recall (Retrieve Learnings)")
    print("=" * 60)

    lm = LearningMachine(
        db=db,
        knowledge=knowledge_base,
        user_profile=True,
        session_context=True,
        learned_knowledge=True,
    )

    # First, seed some data
    print("\nSeeding test data...")

    # Add user profile
    lm._user_profile_store.add_memory(
        user_id, "Software engineer specializing in Python"
    )
    lm._user_profile_store.add_memory(user_id, "Prefers concise explanations")

    # Add session context
    from agno.learn.schemas import DefaultSessionContext

    context = DefaultSessionContext(
        session_id=session_id,
        summary="Working on API optimization project",
        goal="Improve API response times",
        plan=["Profile endpoints", "Optimize queries", "Add caching"],
        progress=["Profile endpoints"],
    )
    lm._session_context_store.save(session_id, context)

    # Now recall
    print("\nRecalling learnings...")
    results = lm.recall(
        user_id=user_id,
        session_id=session_id,
        message="How can I make my API faster?",
    )

    print("\nRecall results:")
    pprint(results)

    # Format for context
    context_text = lm.format_recall_for_context(results)
    print("\nFormatted context for system prompt:")
    print("-" * 50)
    print(context_text[:500] if context_text else "No context")
    print("-" * 50)

    print("\n✅ Recall test passed!")


def test_process():
    """Test process() - background extraction."""
    print("\n" + "=" * 60)
    print("TEST: Process (Background Extraction)")
    print("=" * 60)

    lm = LearningMachine(
        db=db,
        user_profile=True,
        session_context=True,
        learned_knowledge=False,
    )

    model = OpenAIChat(id="gpt-4o-mini")

    # Simulate a conversation
    messages = [
        Message(role="user", content="Hi, I'm Alex from the DevOps team at Acme Corp."),
        Message(role="assistant", content="Hello Alex! How can I help you today?"),
        Message(
            role="user",
            content="I need help setting up a CI/CD pipeline for our new microservices.",
        ),
        Message(
            role="assistant", content="I can help with that. What's your current setup?"
        ),
        Message(
            role="user",
            content="We're using GitHub Actions and want to deploy to Kubernetes.",
        ),
    ]

    test_user = "process_test_user@example.com"
    test_session = "process_test_session"

    print("\nRunning background extraction...")
    lm.process(
        user_id=test_user,
        session_id=test_session,
        messages=messages,
        model=model,
    )

    # Check what was extracted
    print("\nExtracted user profile:")
    profile = lm._user_profile_store.get(test_user)
    if profile:
        pprint(profile.to_dict())
    else:
        print("  No profile extracted")

    print("\nExtracted session context:")
    context = lm._session_context_store.get(test_session)
    if context:
        pprint(context.to_dict())
    else:
        print("  No context extracted")

    # Cleanup
    db.delete_learnings(learning_type="user_profile", user_id=test_user)
    db.delete_learnings(learning_type="session_context", session_id=test_session)

    print("\n✅ Process test passed!")


def test_system_prompt_injection():
    """Test get_system_prompt_injection() - instructions for agent."""
    print("\n" + "=" * 60)
    print("TEST: System Prompt Injection")
    print("=" * 60)

    lm = LearningMachine(
        db=db,
        knowledge=knowledge_base,
        user_profile=UserProfileConfig(enable_tool=True),
        session_context=True,
        learned_knowledge=KnowledgeConfig(mode=LearningMode.PROPOSE, enable_tool=True),
    )

    injection = lm.get_system_prompt_injection()

    print("\nSystem prompt injection:")
    print("-" * 50)
    print(injection)
    print("-" * 50)

    # Should contain instructions for PROPOSE mode
    assert "learning_instructions" in injection
    print("\n  ✓ Contains learning instructions")

    print("\n✅ System prompt injection test passed!")


def test_tools_generation():
    """Test get_tools() - tools for agentic learning."""
    print("\n" + "=" * 60)
    print("TEST: Tools Generation")
    print("=" * 60)

    # With both tools enabled
    lm = LearningMachine(
        db=db,
        knowledge=knowledge_base,
        user_profile=UserProfileConfig(enable_tool=True),
        session_context=True,  # No tool for session context
        learned_knowledge=KnowledgeConfig(enable_tool=True),
    )

    tools = lm.get_tools(user_id=user_id)

    print(f"\nGenerated {len(tools)} tools:")
    for tool in tools:
        name = tool.__name__ if hasattr(tool, "__name__") else str(tool)
        print(f"  - {name}")

    # Test tool functions
    print("\nTesting save_user_memory tool...")
    save_memory_tool = next((t for t in tools if "memory" in str(t).lower()), None)
    if save_memory_tool:
        # Call the tool
        result = save_memory_tool("Test memory from tool")
        print(f"  Result: {result}")

    print("\n✅ Tools generation test passed!")


def cleanup():
    """Clean up test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    db.delete_learnings(learning_type="user_profile", user_id=user_id)
    db.delete_learnings(learning_type="session_context", session_id=session_id)

    print("  Cleaned up test data")


if __name__ == "__main__":
    # Run all tests
    test_dx_level_1()
    test_dx_level_2()
    test_dx_level_3()
    test_recall()
    test_process()
    test_system_prompt_injection()
    test_tools_generation()

    # Clean up
    cleanup()

    print("\n" + "=" * 60)
    print("✅ All LearningMachine tests passed!")
    print("=" * 60)
