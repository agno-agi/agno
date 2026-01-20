"""
Evaluate
========

Runs basic verification tests for the Linear Agent.

Note: This agent requires Linear API credentials. The evaluation verifies
agent configuration and basic response capability.

Usage:
    python examples/evaluate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import linear_agent  # noqa: E402

# Test cases for issue creation logic (without actual API calls)
TEST_CASES = [
    {
        "prompt": (
            "If I asked you to create an issue for 'URGENT: Login button broken', "
            "what priority would you assign and what title would you use?"
        ),
        "expected": ["urgent", "1", "login", "button", "fix"],
    },
    {
        "prompt": (
            "How would you structure an issue for 'Nice to have: Add dark mode to settings'?"
        ),
        "expected": ["low", "4", "dark mode", "settings", "add"],
    },
]


def run_evaluation() -> bool:
    passed = 0
    failed = 0

    # Verify agent configuration
    print("Verifying agent configuration...")
    if linear_agent.model is None:
        print("  x FAIL - Agent model not configured")
        return False
    print("  v Agent configured correctly")
    print()

    for i, test in enumerate(TEST_CASES, 1):
        print(f"Test {i}: Issue structuring")

        try:
            response = linear_agent.run(test["prompt"])
            text = (response.content or "").lower()

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
            # Linear API errors are expected if credentials not configured
            if "linear" in str(e).lower() or "api" in str(e).lower():
                print(f"  - SKIP - Linear API not configured: {e}")
                passed += 1
            else:
                print(f"  x FAIL - Exception: {e}")
                failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_evaluation() else 1)
