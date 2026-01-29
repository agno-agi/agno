"""
Evaluate
========

Runs verification tests for the Contract Review agent.

Usage:
    python examples/evaluate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import contract_agent  # noqa: E402
from agno.media import File  # noqa: E402

DOCS_DIR = Path(__file__).parent.parent / "documents"

TEST_CASES = [
    {
        "name": "NDA term extraction",
        "document": "sample_nda.txt",
        "prompt": "What are the key terms in this NDA? List the parties and confidentiality period.",
        "expected": ["confidential", "party", "disclos"],
    },
    {
        "name": "Risk identification",
        "document": "Risky_Service_Agreement.pdf",
        "prompt": "Identify the top risks in this contract.",
        "expected": ["risk", "liabil", "indemnif"],
    },
]


def run_evaluation() -> bool:
    passed = 0
    failed = 0

    print("Verifying agent configuration...")
    if contract_agent.model is None:
        print("  x FAIL - Agent model not configured")
        return False
    print("  v Agent configured correctly")
    print()

    for i, test in enumerate(TEST_CASES, 1):
        print(f"Test {i}: {test['name']}")

        try:
            doc_path = DOCS_DIR / test["document"]
            response = contract_agent.run(
                test["prompt"],
                files=[File(filepath=doc_path)],
            )
            text = str(response.content).lower() if response.content else ""

            found = [e for e in test["expected"] if e.lower() in text]

            if len(found) >= 2:
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
