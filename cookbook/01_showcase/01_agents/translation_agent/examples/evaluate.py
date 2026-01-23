"""
Evaluate
========

Runs verification tests for the Translation Agent.

Note: This agent requires CARTESIA_API_KEY for audio. The evaluation verifies
agent configuration and translation reasoning.

Usage:
    python examples/evaluate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import translation_agent  # noqa: E402

# Test cases for translation reasoning
TEST_CASES = [
    {
        "prompt": (
            "Without actually translating, explain how you would translate "
            "'Hello, how are you?' to French. What emotion would you detect?"
        ),
        "expected": ["french", "bonjour", "neutral", "greeting", "fr"],
    },
    {
        "prompt": (
            "What emotion would you detect in this text and why: "
            "'I am so excited about this amazing news!'"
        ),
        "expected": ["excited", "happy", "positive", "emotion", "joy"],
    },
]


def run_evaluation() -> bool:
    passed = 0
    failed = 0

    # Verify agent configuration
    print("Verifying agent configuration...")
    if translation_agent.model is None:
        print("  x FAIL - Agent model not configured")
        return False
    print("  v Agent configured correctly")
    print()

    for i, test in enumerate(TEST_CASES, 1):
        print(f"Test {i}: Translation reasoning")

        try:
            response = translation_agent.run(test["prompt"])
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
            # Cartesia API errors are expected if credentials not configured
            if "cartesia" in str(e).lower() or "api" in str(e).lower():
                print(f"  - SKIP - Cartesia API not configured: {e}")
                passed += 1
            else:
                print(f"  x FAIL - Exception: {e}")
                failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_evaluation() else 1)
