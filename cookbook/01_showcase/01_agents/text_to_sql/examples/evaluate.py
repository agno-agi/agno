"""
Evaluate
========

Runs test queries and verifies expected results.

Usage:
    python scripts/evaluate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import sql_agent

TEST_CASES = [
    ("Who won the most races in 2019?", ["Lewis Hamilton", "11"]),
    ("Which team won the 2020 constructors championship?", ["Mercedes"]),
    ("Who won the 2020 drivers championship?", ["Lewis Hamilton"]),
    ("Which driver has won the most world championships?", ["Michael Schumacher", "7"]),
    ("Which constructor has won the most championships?", ["Ferrari"]),
    ("Who has the most fastest laps at Monaco?", ["Michael Schumacher"]),
]


def run_evaluation() -> bool:
    passed = 0
    failed = 0

    for question, expected in TEST_CASES:
        response = sql_agent.run(question)
        text = (response.content or "").lower()

        missing = [e for e in expected if e.lower() not in text]

        if missing:
            print(f"✗ {question}")
            print(f"  Missing: {missing}")
            failed += 1
        else:
            print(f"✓ {question}")
            passed += 1

    print(f"\n{passed}/{passed + failed} passed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_evaluation() else 1)
