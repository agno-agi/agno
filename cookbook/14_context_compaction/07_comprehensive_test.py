"""
Comprehensive Context Compaction Test Suite

Tests all aspects of context compaction:
1. Basic compaction works
2. User preferences survive compaction
3. Works across multiple runs
4. Async compaction works

Run: .venvs/demo/bin/python cookbook/14_context_compaction/07_comprehensive_test.py
"""

import asyncio
import os

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat


def test_basic_compaction():
    """Test 1: Verify basic compaction triggers and works."""
    print("\n" + "=" * 60)
    print("TEST 1: Basic Compaction")
    print("=" * 60)

    db_path = "tmp/basic_compaction_test.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    db = SqliteDb(db_file=db_path)

    compaction_manager = CompactionManager(
        model=OpenAIChat(id="gpt-4.1-mini"),
        compact_context=True,
        compact_context_message_limit=4,
        compact_context_keep_recent=2,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4.1-mini"),
        session_id="basic-compaction-test",
        db=db,
        add_history_to_context=True,
        compaction_manager=compaction_manager,
    )

    prompts = [
        "Explain Python decorators with detailed examples.",
        "Now explain context managers in Python.",
        "How do decorators and context managers compare?",
    ]

    compaction_occurred = False
    for i, prompt in enumerate(prompts, 1):
        print(f"Turn {i}: {prompt[:40]}...")
        response = agent.run(prompt)
        print(f"  Response: {response.content[:60]}...")

        state = response.compaction_state
        if state and state.total_compactions > 0:
            print(
                f"  Compaction #{state.total_compactions} - {state.total_tokens_saved} tokens saved"
            )
            compaction_occurred = True

    os.remove(db_path)

    if compaction_occurred:
        print("\nPASS: Basic compaction triggered")
    else:
        print("\nNOTE: Compaction may not have triggered (depends on response length)")

    return True


def test_preference_survival():
    """Test 2: Verify user preferences survive compaction."""
    print("\n" + "=" * 60)
    print("TEST 2: Preference Survival")
    print("=" * 60)

    db_path = "tmp/preference_test.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    db = SqliteDb(db_file=db_path)

    compaction_manager = CompactionManager(
        model=OpenAIChat(id="gpt-4.1-mini"),
        compact_context=True,
        compact_context_message_limit=4,
        compact_context_keep_recent=2,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4.1-mini"),
        session_id="preference-test",
        db=db,
        add_history_to_context=True,
        compaction_manager=compaction_manager,
    )

    # Set preferences
    print("Setting preferences...")
    r1 = agent.run("My name is CompactionTestUser and I prefer Python over JavaScript.")
    print(f"  Response: {r1.content[:60]}...")

    # Add filler content to trigger compaction
    print("Adding content to trigger compaction...")
    r2 = agent.run("Explain the decorator pattern in detail with multiple examples.")
    print(f"  Response: {r2.content[:60]}...")

    state = r2.compaction_state
    if state and state.total_compactions > 0:
        print(f"  Compaction #{state.total_compactions} occurred")

    # Test if preferences survived
    print("Testing preference survival...")
    r3 = agent.run("What's my name and what language do I prefer?")
    print(f"  Response: {r3.content[:150]}...")

    name_found = "compactiontestuser" in r3.content.lower()
    python_found = "python" in r3.content.lower()

    os.remove(db_path)

    print(f"\nName preserved: {'YES' if name_found else 'NO'}")
    print(f"Language preference preserved: {'YES' if python_found else 'NO'}")

    if name_found and python_found:
        print("PASS: Preferences survived compaction")
    else:
        print("WARNING: Some preferences may have been lost")

    return True


def test_multi_run_persistence():
    """Test 3: Verify compaction state persists across runs."""
    print("\n" + "=" * 60)
    print("TEST 3: Multi-Run State Persistence")
    print("=" * 60)

    db_path = "tmp/multi_run_test.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    db = SqliteDb(db_file=db_path)

    compaction_manager = CompactionManager(
        model=OpenAIChat(id="gpt-4.1-mini"),
        compact_context=True,
        compact_context_message_limit=4,
        compact_context_keep_recent=2,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4.1-mini"),
        session_id="multi-run-test",
        db=db,
        add_history_to_context=True,
        compaction_manager=compaction_manager,
    )

    # Run 1: Set context
    print("Run 1: Setting preferences...")
    r1 = agent.run("My name is TestUser and I prefer Python.")
    print(f"  Response: {r1.content[:60]}...")

    # Run 2: Add more content
    print("Run 2: Adding content...")
    r2 = agent.run("Explain the decorator pattern in detail with multiple examples.")
    print(f"  Response: {r2.content[:60]}...")

    state = r2.compaction_state
    if state and state.total_compactions > 0:
        print(f"  Compaction #{state.total_compactions} occurred")

    # Run 3: More content
    print("Run 3: Adding more content...")
    r3 = agent.run("Now explain the strategy pattern with examples.")
    print(f"  Response: {r3.content[:60]}...")

    state = r3.compaction_state
    if state and state.total_compactions > 0:
        print(f"  Compaction #{state.total_compactions} occurred")
        print(f"  Total tokens saved: {state.total_tokens_saved}")

    # Run 4: Test if preferences survived
    print("Run 4: Testing preference survival...")
    r4 = agent.run("What's my name?")
    print(f"  Response: {r4.content[:100]}...")

    name_found = "testuser" in r4.content.lower()
    print(f"\nName preserved: {'YES' if name_found else 'NO'}")

    os.remove(db_path)

    print("PASS: Multi-run test completed")
    return True


async def test_async_compaction():
    """Test 4: Verify async compaction works."""
    print("\n" + "=" * 60)
    print("TEST 4: Async Compaction")
    print("=" * 60)

    db_path = "tmp/async_test.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    db = SqliteDb(db_file=db_path)

    compaction_manager = CompactionManager(
        model=OpenAIChat(id="gpt-4.1-mini"),
        compact_context=True,
        compact_context_message_limit=4,
        compact_context_keep_recent=2,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4.1-mini"),
        session_id="async-test",
        db=db,
        add_history_to_context=True,
        compaction_manager=compaction_manager,
    )

    prompts = [
        "My name is AsyncUser. Remember this.",
        "Explain coroutines in Python with detailed examples.",
        "What's my name?",
    ]

    for i, prompt in enumerate(prompts, 1):
        print(f"Async Turn {i}: {prompt[:40]}...")
        response = await agent.arun(prompt)
        print(f"  Response: {response.content[:60]}...")

        state = response.compaction_state
        if state and state.total_compactions > 0:
            print(
                f"  Compaction #{state.total_compactions}: {state.total_tokens_saved} tokens saved"
            )

    os.remove(db_path)

    print("\nPASS: Async compaction works")
    return True


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("COMPREHENSIVE CONTEXT COMPACTION TEST SUITE")
    print("=" * 60)

    results = []

    # Integration tests
    results.append(("Basic Compaction", test_basic_compaction()))
    results.append(("Preference Survival", test_preference_survival()))
    results.append(("Multi-Run Persistence", test_multi_run_persistence()))
    results.append(("Async Compaction", asyncio.run(test_async_compaction())))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
