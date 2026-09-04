"""
Multi-Model Context Compaction Test

Tests compaction with different model combinations:
1. Agent model = OpenAI, Compaction model = OpenAI (default)
2. Agent model = OpenAI, Compaction model = Claude
3. Agent model = Claude, Compaction model = GPT-4.1-mini
4. Agent model = Gemini, Compaction model = OpenAI

Run: .venvs/demo/bin/python cookbook/14_context_compaction/09_multi_model_test.py
"""

import os
import tempfile
from typing import Optional

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.base import Model
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat


def run_compaction_test(
    name: str,
    agent_model: Model,
    compaction_model: Optional[Model] = None,
) -> bool:
    """Run a compaction test with specified models."""
    print("=" * 60)
    print(f"TEST: {name}")
    print("=" * 60)
    print(f"  Agent model: {agent_model.id}")
    if compaction_model:
        print(f"  Compaction model: {compaction_model.id}")
    else:
        print("  Compaction model: (same as agent)")

    # Use temp file for database
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = db_file.name
    db_file.close()

    db = SqliteDb(db_file=db_path)

    # Create compaction manager - use compaction_model if provided, else agent_model
    compaction_manager = CompactionManager(
        model=compaction_model or agent_model,
        compact_context=True,
        compact_context_message_limit=4,
        compact_context_keep_recent=2,
    )

    agent = Agent(
        model=agent_model,
        compaction_manager=compaction_manager,
        session_id=f"test-{name.lower().replace(' ', '-')}",
        db=db,
        add_history_to_context=True,
    )

    prompts = [
        "My name is MultiModelUser and I work on quantum computing research.",
        "Explain quantum entanglement with detailed mathematical examples.",
        "What's my name and what do I research?",
    ]

    last_response = None
    for i, prompt in enumerate(prompts, 1):
        print(f"\n  Turn {i}: {prompt[:50]}...")
        try:
            response = agent.run(prompt)
            last_response = response
            print(f"    Response: {response.content[:60]}...")

            state = response.compaction_state
            if state and state.total_compactions > 0:
                print(
                    f"    [Compaction #{state.total_compactions}] {state.total_tokens_saved} tokens saved"
                )
        except Exception as e:
            print(f"    ERROR: {e}")
            os.remove(db_path)
            return False

    # Verify name survived
    name_found = last_response and "multimodeluser" in last_response.content.lower()
    quantum_found = last_response and "quantum" in last_response.content.lower()

    print(f"\n  Name preserved: {'YES' if name_found else 'NO'}")
    print(f"  Context preserved: {'YES' if quantum_found else 'NO'}")

    os.remove(db_path)

    return name_found


def main():
    print("MULTI-MODEL CONTEXT COMPACTION TESTS")
    print("=" * 60)
    print()

    results = []

    # Test 1: OpenAI agent with default compaction (same model)
    results.append(
        (
            "OpenAI Default",
            run_compaction_test(
                name="OpenAI Default",
                agent_model=OpenAIChat(id="gpt-4.1-mini"),
            ),
        )
    )

    # Test 2: OpenAI agent with Claude as compaction model
    results.append(
        (
            "OpenAI + Claude Compactor",
            run_compaction_test(
                name="OpenAI + Claude Compactor",
                agent_model=OpenAIChat(id="gpt-4.1-mini"),
                compaction_model=Claude(id="claude-sonnet-4-5-20250929"),
            ),
        )
    )

    # Test 3: Claude agent with GPT-4.1-mini as compaction model
    results.append(
        (
            "Claude + GPT Compactor",
            run_compaction_test(
                name="Claude + GPT Compactor",
                agent_model=Claude(id="claude-sonnet-4-5-20250929"),
                compaction_model=OpenAIChat(id="gpt-4.1-mini"),
            ),
        )
    )

    # Test 4: Gemini agent with OpenAI compaction
    results.append(
        (
            "Gemini + OpenAI Compactor",
            run_compaction_test(
                name="Gemini + OpenAI Compactor",
                agent_model=Gemini(id="gemini-2.5-flash"),
                compaction_model=OpenAIChat(id="gpt-4.1-mini"),
            ),
        )
    )

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {name}")

    passed_count = sum(1 for _, r in results if r)
    print(f"\nTotal: {passed_count}/{len(results)} tests passed")

    return passed_count == len(results)


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
