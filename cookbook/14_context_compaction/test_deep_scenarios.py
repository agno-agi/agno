"""
Deep Testing: Context Compaction Scenarios

Tests multiple scenarios:
1. Multi-run accumulation (many agent.run() calls)
2. Single long run with tool loop (continuous within one run)
3. Session persistence (reload and continue)
4. Mid-run compaction (compaction during tool loop)

Run: AGNO_DEBUG=true .venvs/demo/bin/python cookbook/14_context_compaction/test_deep_scenarios.py
"""

import os
import sys

os.environ["AGNO_DEBUG"] = "true"

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.exa import ExaTools
from agno.utils.log import log_info

DB_PATH = "tmp/dbs/deep_test.db"
SESSION_ID = "deep-test-session"
CONTEXT_WINDOW = 2000
THRESHOLD = 0.3  # 30% = 600 tokens - low to trigger compaction quickly


def create_agent(session_id: str = SESSION_ID):
    db = SqliteDb(db_file=DB_PATH)
    compression_manager = CompressionManager(
        model=OpenAIResponses(id="gpt-4o-mini"),
        context_compaction=True,
        context_compaction_threshold=THRESHOLD,
        context_window=CONTEXT_WINDOW,
        keep_recent_messages=4,
        user_message_budget_fraction=0.15,
    )
    return Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[ExaTools()],
        compression_manager=compression_manager,
        db=db,
        session_id=session_id,
        add_history_to_context=True,
        num_history_runs=50,
    )


def test_multi_run_accumulation():
    """Test: Many separate agent.run() calls accumulate and trigger compaction."""
    print("\n" + "=" * 60)
    print("TEST 1: Multi-Run Accumulation")
    print("=" * 60)

    agent = create_agent("test-multi-run")

    queries = [
        "Search for recent Python 3.13 release news and features",
        "Search for latest machine learning frameworks comparison",
        "Search for cloud computing trends 2024",
    ]

    for i, query in enumerate(queries, 1):
        print(f"\n[Run {i}] {query}")
        response = agent.run(query)
        content = response.content or ""
        print(f"Response: {content[:100]}...")

        stats = agent.compression_manager.stats
        if stats.get("compactions", 0) > 0:
            print(f"  -> Compactions so far: {stats['compactions']}")
            print(f"  -> Messages compacted: {stats['messages_compacted']}")

    print(f"\nFinal stats: {agent.compression_manager.stats}")
    return agent.compression_manager.stats.get("compactions", 0) > 0


def test_single_long_run():
    """Test: Single run with a query that triggers multiple tool calls."""
    print("\n" + "=" * 60)
    print("TEST 2: Single Long Run (Multi-Tool)")
    print("=" * 60)

    agent = create_agent("test-single-long-run")

    # Query that triggers multiple searches
    query = """Search for these topics and give detailed summaries:
    1. Python 3.13 new features
    2. TypeScript vs JavaScript performance
    3. Rust programming language adoption
    Give comprehensive summaries for each."""

    print(f"\n[Single Run] {query[:60]}...")
    response = agent.run(query)
    content = response.content or ""
    print(f"Response: {content[:200]}...")

    stats = agent.compression_manager.stats
    print(f"\nFinal stats: {stats}")
    return True  # Just verify it completes


def test_session_persistence():
    """Test: Save session, reload, continue - compaction state persists."""
    print("\n" + "=" * 60)
    print("TEST 3: Session Persistence")
    print("=" * 60)

    session_id = "test-persistence"

    # Phase 1: Create session and run some queries
    print("\n[Phase 1] Initial session")
    agent1 = create_agent(session_id)

    queries = [
        "Search for Python async programming best practices",
        "Search for FastAPI vs Django comparison",
        "Search for PostgreSQL optimization tips",
    ]
    for i, query in enumerate(queries):
        agent1.run(query)
        print(f"  Run {i + 1} complete")

    stats1 = dict(agent1.compression_manager.stats)
    print(f"Stats after phase 1: {stats1}")

    # Phase 2: Create NEW agent with same session_id (simulates restart)
    print("\n[Phase 2] Reload session")
    agent2 = create_agent(session_id)

    # Run more queries - should load history and trigger compaction
    more_queries = [
        "Search for Redis caching strategies",
        "Search for Docker container best practices",
        "Search for Kubernetes deployment patterns",
    ]
    for i, query in enumerate(more_queries, start=4):
        agent2.run(query)
        print(f"  Run {i} complete")

    stats2 = agent2.compression_manager.stats
    print(f"Stats after phase 2: {stats2}")

    # Compaction happened if stats show it
    compactions = stats2.get("compactions", 0)
    print(f"\nTotal compactions in phase 2: {compactions}")
    return compactions > 0


def test_tool_call_pair_safety():
    """Test: Tool calls and results stay together (not split during compaction)."""
    print("\n" + "=" * 60)
    print("TEST 4: Tool Call Pair Safety")
    print("=" * 60)

    agent = create_agent("test-tool-pairs")

    # Run multiple search queries
    queries = [
        "Search for microservices architecture patterns",
        "Search for GraphQL vs REST API comparison",
        "Search for serverless computing pros and cons",
    ]
    for query in queries:
        agent.run(query)

    # If we got here without API errors, tool pairs weren't orphaned
    print("No API errors - tool call pairs stayed together")
    return True


def run_all_tests():
    """Run all test scenarios."""
    print("Context Compaction Deep Testing")
    print(f"Context window: {CONTEXT_WINDOW} tokens")
    print(
        f"Threshold: {int(THRESHOLD * 100)}% ({int(CONTEXT_WINDOW * THRESHOLD)} tokens)"
    )

    results = {}

    try:
        results["multi_run"] = test_multi_run_accumulation()
    except Exception as e:
        print(f"TEST 1 FAILED: {e}")
        results["multi_run"] = False

    try:
        results["single_long_run"] = test_single_long_run()
    except Exception as e:
        print(f"TEST 2 FAILED: {e}")
        results["single_long_run"] = False

    try:
        results["persistence"] = test_session_persistence()
    except Exception as e:
        print(f"TEST 3 FAILED: {e}")
        results["persistence"] = False

    try:
        results["tool_pairs"] = test_tool_call_pair_safety()
    except Exception as e:
        print(f"TEST 4 FAILED: {e}")
        results["tool_pairs"] = False

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for test, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test}: {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    return all_passed


if __name__ == "__main__":
    # Clean start
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing {DB_PATH}")

    success = run_all_tests()
    sys.exit(0 if success else 1)
