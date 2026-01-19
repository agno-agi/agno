"""
Evaluate Agent Accuracy
=======================

Tests the recipe agent's ability to retrieve and present recipes.

This is useful for:
- Regression testing after changes
- Validating knowledge retrieval
- Benchmarking agent performance

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load recipes: python scripts/load_recipes.py
    Run: python scripts/check_setup.py

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

from agent import recipe_agent  # noqa: E402

# ============================================================================
# Test Cases
# ============================================================================
TEST_CASES = [
    {
        "name": "recipe_search",
        "query": "What is a good Thai curry recipe?",
        "expected_contains": ["curry", "coconut"],
        "description": "Tests knowledge base search for recipes",
    },
]


# ============================================================================
# Evaluation Functions
# ============================================================================
def run_test(test_case: dict, verbose: bool = True) -> dict[str, Any]:
    """Run a single test case and check results."""
    name = test_case["name"]
    query = test_case["query"]

    if verbose:
        print(f"\n  Testing: {name}")
        print(f"  Query: {query}")

    try:
        # Run the agent
        response = recipe_agent.run(query)
        response_text = response.content if response else ""

        if not response_text:
            if verbose:
                print("  [FAIL] No response from agent")
            return {"name": name, "passed": False, "error": "No response"}

        # Check expected content
        response_lower = response_text.lower()
        found = []
        missing = []
        for expected in test_case["expected_contains"]:
            if expected.lower() in response_lower:
                found.append(expected)
            else:
                missing.append(expected)

        passed = len(missing) == 0

        if verbose:
            if passed:
                print("  [PASS]")
                print(f"    Response length: {len(response_text)} chars")
                print(f"    Found keywords: {found}")
            else:
                print("  [FAIL]")
                print(f"    Missing keywords: {missing}")
                print(f"    Found: {found}")

        return {
            "name": name,
            "passed": passed,
            "response_length": len(response_text),
            "found": found,
            "missing": missing,
        }

    except Exception as e:
        if verbose:
            print(f"  [FAIL] Error: {e}")
        return {
            "name": name,
            "passed": False,
            "error": str(e),
        }


def run_evaluation(verbose: bool = True) -> dict[str, Any]:
    """Run all test cases and return summary."""
    if verbose:
        print("=" * 60)
        print("Recipe Agent - Evaluation")
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
                    error = r.get("error", "See details above")
                    print(f"    - {r['name']}: {error}")

    return summary


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Recipe Agent - Evaluation Suite")
    print("=" * 60)
    print(
        """
This script tests the recipe agent's ability to:
  - Search the knowledge base for recipes
  - Present recipe information clearly
  - Include relevant cooking instructions

Prerequisites:
  - PostgreSQL running with PgVector
  - Recipes loaded into knowledge base
"""
    )

    summary = run_evaluation(verbose=True)

    # Exit with appropriate code
    sys.exit(0 if summary["failed"] == 0 else 1)
