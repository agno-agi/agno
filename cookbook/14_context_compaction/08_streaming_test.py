"""
Streaming Context Compaction Test

Tests that compaction works correctly with streaming responses.

Run: .venvs/demo/bin/python cookbook/14_context_compaction/08_streaming_test.py
"""

import os

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat


def test_sync_streaming():
    """Test compaction with sync streaming."""
    print("=" * 60)
    print("TEST: Sync Streaming Compaction")
    print("=" * 60)

    db_path = "tmp/streaming_test.db"
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
        session_id="streaming-test",
        db=db,
        add_history_to_context=True,
        compaction_manager=compaction_manager,
    )

    prompts = [
        "My name is StreamUser and I work on distributed systems.",
        "Explain the Raft consensus algorithm with detailed examples.",
        "What's my name and what do I work on?",
    ]

    for i, prompt in enumerate(prompts, 1):
        print(f"\nTurn {i}: {prompt[:50]}...")
        print("  Streaming: ", end="", flush=True)

        full_response = ""
        for chunk in agent.run(prompt, stream=True):
            if hasattr(chunk, "content") and chunk.content:
                print(".", end="", flush=True)
                full_response += chunk.content

        print()
        print(f"  Response: {full_response[:80]}...")

        # Get compaction state from the last run output
        run_output = agent.get_last_run_output(session_id="streaming-test")
        if run_output and run_output.compaction_state:
            state = run_output.compaction_state
            if state.total_compactions > 0:
                print(
                    f"  [Compaction #{state.total_compactions}] {state.total_tokens_saved} tokens saved"
                )

    # Verify name survived
    name_found = "streamuser" in full_response.lower()
    distributed_found = "distributed" in full_response.lower()

    print(f"\nName preserved: {'YES' if name_found else 'NO'}")
    print(f"Work context preserved: {'YES' if distributed_found else 'NO'}")

    os.remove(db_path)

    return name_found


async def test_async_streaming():
    """Test compaction with async streaming."""
    print("\n" + "=" * 60)
    print("TEST: Async Streaming Compaction")
    print("=" * 60)

    db_path = "tmp/async_streaming_test.db"
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
        session_id="async-streaming-test",
        db=db,
        add_history_to_context=True,
        compaction_manager=compaction_manager,
    )

    prompts = [
        "My name is AsyncStreamUser and I build ML pipelines.",
        "Explain gradient descent optimization with mathematical details.",
        "What's my name and what do I build?",
    ]

    for i, prompt in enumerate(prompts, 1):
        print(f"\nTurn {i}: {prompt[:50]}...")
        print("  Streaming: ", end="", flush=True)

        full_response = ""
        async for chunk in agent.arun(prompt, stream=True):
            if hasattr(chunk, "content") and chunk.content:
                print(".", end="", flush=True)
                full_response += chunk.content

        print()
        print(f"  Response: {full_response[:80]}...")

        # Get compaction state from the last run output
        run_output = agent.get_last_run_output(session_id="async-streaming-test")
        if run_output and run_output.compaction_state:
            state = run_output.compaction_state
            if state.total_compactions > 0:
                print(
                    f"  [Compaction #{state.total_compactions}] {state.total_tokens_saved} tokens saved"
                )

    # Verify name survived
    name_found = "asyncstreamuser" in full_response.lower()
    ml_found = "ml" in full_response.lower() or "pipeline" in full_response.lower()

    print(f"\nName preserved: {'YES' if name_found else 'NO'}")
    print(f"Work context preserved: {'YES' if ml_found else 'NO'}")

    os.remove(db_path)

    return name_found


def main():
    import asyncio

    print("STREAMING COMPACTION TESTS")
    print("=" * 60)

    results = []

    # Sync streaming
    results.append(("Sync Streaming", test_sync_streaming()))

    # Async streaming
    results.append(("Async Streaming", asyncio.run(test_async_streaming())))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {name}")

    all_passed = all(r for _, r in results)
    print(f"\nTotal: {sum(1 for _, r in results if r)}/{len(results)} tests passed")

    return all_passed


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
