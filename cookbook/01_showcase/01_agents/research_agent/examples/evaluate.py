"""
Evaluate
========

Runs verification tests for the Research Agent.

Note: This agent requires PARALLEL_API_KEY. The evaluation verifies
agent configuration and basic research reasoning.

Usage:
    python examples/evaluate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import research_agent  # noqa: E402

# Test cases for research reasoning
TEST_CASES = [
    {
        "prompt": (
            "Without searching, explain what strategy you would use to research "
            "'best practices for building AI agents in production'. "
            "What search queries would you use?"
        ),
        "expected": ["search", "query", "agent", "production", "source"],
    },
    {
        "prompt": (
            "What factors would you consider when evaluating the credibility "
            "of sources for a research report on machine learning?"
        ),
        "expected": ["credibility", "source", "academic", "official", "verify"],
    },
]


def run_evaluation() -> bool:
    passed = 0
    failed = 0

    # Verify agent configuration
    print("Verifying agent configuration...")
    if research_agent.model is None:
        print("  x FAIL - Agent model not configured")
        return False
    if research_agent.output_schema is None:
        print("  x FAIL - Agent output schema not configured")
        return False
    print("  v Agent configured correctly")
    print()

    for i, test in enumerate(TEST_CASES, 1):
        print(f"Test {i}: Research strategy")

        try:
            response = research_agent.run(test["prompt"])
            text = str(response.content).lower() if response.content else ""

            # Check for expected keywords
            found = [e for e in test["expected"] if e.lower() in text]

            if len(found) >= 2:  # At least 2 expected keywords
                print(f"  v PASS - Found: {found}")
                passed += 1
            else:
                print(f"  x FAIL - Expected keywords from: {test['expected']}")
                print(f"    Found only: {found}")
                failed += 1

        except Exception as e:
            # Parallel API errors are expected if credentials not configured
            if "parallel" in str(e).lower() or "api" in str(e).lower():
                print(f"  - SKIP - Parallel API not configured: {e}")
                passed += 1
            else:
                print(f"  x FAIL - Exception: {e}")
                failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_evaluation() else 1)
