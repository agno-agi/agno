"""
Evaluate Agent Accuracy
=======================

Runs a standard set of queries and verifies the agent returns expected results.

This is useful for:
- Regression testing after changes
- Validating knowledge base improvements
- Benchmarking agent performance

Test cases cover:
- Simple aggregations
- Filtering queries
- Multi-table joins
- Data quality handling (TEXT vs INT positions)

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load F1 data: python scripts/load_f1_data.py
    3. Load knowledge: python scripts/load_knowledge.py

    Or run: python scripts/check_setup.py

Usage:
    python scripts/evaluate.py
"""

import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import sql_agent  # noqa: E402

# ============================================================================
# Test Cases
# ============================================================================
TEST_CASES = [
    {
        "name": "most_race_wins_2019",
        "question": "Who won the most races in 2019?",
        "expected_contains": ["Lewis Hamilton", "11"],
        "tests_data_quality": "DATE parsing in race_wins",
    },
    {
        "name": "constructors_champion_2020",
        "question": "Which team won the 2020 constructors championship?",
        "expected_contains": ["Mercedes"],
        "tests_data_quality": "INTEGER position in constructors_championship",
    },
    {
        "name": "drivers_champion_2020",
        "question": "Who won the 2020 drivers championship?",
        "expected_contains": ["Lewis Hamilton"],
        "tests_data_quality": "TEXT position in drivers_championship (position = '1')",
    },
    {
        "name": "most_championships_driver",
        "question": "Which driver has won the most world championships?",
        "expected_contains": ["Michael Schumacher", "7"],
        "tests_data_quality": "TEXT position aggregation",
    },
    {
        "name": "most_championships_constructor",
        "question": "Which constructor has won the most championships?",
        "expected_contains": ["Ferrari"],
        "tests_data_quality": "INTEGER position aggregation",
    },
    {
        "name": "monaco_fastest_laps",
        "question": "Who has the most fastest laps at Monaco?",
        "expected_contains": ["Michael Schumacher"],
        "tests_data_quality": "venue filtering, driver_tag column",
    },
]


# ============================================================================
# Evaluation Functions
# ============================================================================
def run_test(test_case: dict, verbose: bool = True) -> dict[str, Any]:
    """Run a single test case and check results.

    Args:
        test_case: Test case dictionary with question and expected values
        verbose: Whether to print detailed output

    Returns:
        dict with test results
    """
    name = test_case["name"]
    question = test_case["question"]
    expected = test_case["expected_contains"]

    if verbose:
        print(f"\n  Testing: {name}")
        print(f"  Question: {question}")

    # Get agent response
    response = sql_agent.run(question)
    response_text = response.content if response else ""

    # Check if expected values are in response
    found = []
    missing = []
    for expected_value in expected:
        if expected_value.lower() in response_text.lower():
            found.append(expected_value)
        else:
            missing.append(expected_value)

    passed = len(missing) == 0

    if verbose:
        if passed:
            print(f"  ✓ PASS - Found: {found}")
        else:
            print(f"  ✗ FAIL - Missing: {missing}")
            print(f"    Found: {found}")

    return {
        "name": name,
        "passed": passed,
        "found": found,
        "missing": missing,
        "response_length": len(response_text),
    }


def run_evaluation(verbose: bool = True) -> dict[str, Any]:
    """Run all test cases and return summary.

    Args:
        verbose: Whether to print detailed output

    Returns:
        dict with evaluation summary
    """
    if verbose:
        print("=" * 60)
        print("Text-to-SQL Agent - Evaluation")
        print("=" * 60)
        print(f"\nRunning {len(TEST_CASES)} test cases...")

    results = []
    for test_case in TEST_CASES:
        result = run_test(test_case, verbose=verbose)
        results.append(result)

    # Calculate summary
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    pass_rate = (passed / len(results)) * 100 if results else 0

    summary = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "results": results,
    }

    if verbose:
        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"\n  Total:     {summary['total']}")
        print(f"  Passed:    {summary['passed']}")
        print(f"  Failed:    {summary['failed']}")
        print(f"  Pass Rate: {summary['pass_rate']:.1f}%")

        if failed > 0:
            print("\n  Failed tests:")
            for r in results:
                if not r["passed"]:
                    print(f"    - {r['name']}: missing {r['missing']}")

    return summary


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Text-to-SQL Agent - Evaluation Suite")
    print("=" * 60)
    print(
        """
This script runs a set of test queries to verify agent accuracy.

Each test checks that expected values appear in the agent's response.
Tests cover various data quality scenarios:
  - DATE parsing in race_wins
  - TEXT vs INTEGER position handling
  - Column name variations (driver_tag vs name_tag)
"""
    )

    summary = run_evaluation(verbose=True)

    # Exit with appropriate code
    sys.exit(0 if summary["failed"] == 0 else 1)
