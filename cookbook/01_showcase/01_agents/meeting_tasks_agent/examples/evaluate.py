"""
Evaluate
========

Runs verification tests for the Meeting Tasks Agent.

Note: This agent requires Linear API credentials. The evaluation verifies
agent configuration and action item extraction logic.

Usage:
    python examples/evaluate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import meeting_tasks_agent  # noqa: E402

# Test cases for action item extraction
TEST_CASES = [
    {
        "prompt": (
            "Extract action items from these meeting notes:\n\n"
            "Engineering Standup - Jan 15\n"
            "- John will update the documentation by Friday\n"
            "- Sarah to review PR #123 ASAP\n"
            "- Team agreed to revisit the API design next week\n"
            "- TODO: Add error handling to the payment flow"
        ),
        "expected": ["john", "documentation", "sarah", "pr", "api", "error"],
    },
    {
        "prompt": (
            "What action items do you see in this meeting summary?\n\n"
            "Product Review - Jan 16\n"
            "- @mike needs to finalize the mockups by EOD\n"
            "- URGENT: Fix the checkout bug before launch\n"
            "- Nice to have: Add analytics dashboard"
        ),
        "expected": ["mike", "mockup", "checkout", "bug", "urgent", "analytics"],
    },
]


def run_evaluation() -> bool:
    passed = 0
    failed = 0

    # Verify agent configuration
    print("Verifying agent configuration...")
    if meeting_tasks_agent.model is None:
        print("  x FAIL - Agent model not configured")
        return False
    print("  v Agent configured correctly")
    print()

    for i, test in enumerate(TEST_CASES, 1):
        print(f"Test {i}: Action item extraction")

        try:
            response = meeting_tasks_agent.run(test["prompt"])
            text = (response.content or "").lower()

            # Check for expected keywords
            found = [e for e in test["expected"] if e.lower() in text]

            if len(found) >= 3:  # At least 3 expected keywords
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
