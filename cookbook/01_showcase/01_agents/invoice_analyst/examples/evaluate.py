"""
Evaluate
========

Runs verification tests for the Invoice Analyst agent.

Note: This agent uses vision capabilities. The evaluation tests
basic reasoning without actual invoice files.

Usage:
    python examples/evaluate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import invoice_agent  # noqa: E402

# Test cases for invoice parsing logic
TEST_CASES = [
    {
        "prompt": (
            "Given this invoice text, what fields would you extract?\n\n"
            "Invoice #: INV-2024-001\n"
            "Date: January 15, 2024\n"
            "Due Date: February 15, 2024\n"
            "From: Acme Corp\n"
            "To: Customer Inc\n\n"
            "Item: Consulting Services - 10 hours @ $150/hr = $1,500.00\n"
            "Item: Software License - 1 @ $500.00 = $500.00\n\n"
            "Subtotal: $2,000.00\n"
            "Tax (8%): $160.00\n"
            "Total: $2,160.00"
        ),
        "expected": ["INV-2024-001", "2160", "Acme", "1500", "500"],
    },
    {
        "prompt": (
            "What validation issues would you flag for this invoice?\n\n"
            "Invoice #: 12345\n"
            "Item: Widget - 5 @ $10 = $60\n"  # Math error: should be $50
            "Total: $60"
        ),
        "expected": ["mismatch", "discrepancy", "error", "50", "60"],
    },
]


def run_evaluation() -> bool:
    passed = 0
    failed = 0

    # Verify agent configuration
    print("Verifying agent configuration...")
    if invoice_agent.model is None:
        print("  x FAIL - Agent model not configured")
        return False
    if invoice_agent.output_schema is None:
        print("  x FAIL - Agent output schema not configured")
        return False
    print("  v Agent configured correctly")
    print()

    for i, test in enumerate(TEST_CASES, 1):
        print(f"Test {i}: Invoice extraction")

        try:
            response = invoice_agent.run(test["prompt"])
            text = str(response.content).lower() if response.content else ""

            # Check for expected values
            found = [e for e in test["expected"] if e.lower() in text]

            if len(found) >= 2:  # At least 2 expected values
                print(f"  v PASS - Found: {found}")
                passed += 1
            else:
                print(f"  x FAIL - Expected values from: {test['expected']}")
                print(f"    Found only: {found}")
                failed += 1

        except Exception as e:
            print(f"  x FAIL - Exception: {e}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_evaluation() else 1)
