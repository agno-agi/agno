"""
Evaluate Agent Accuracy
=======================

Runs research queries and verifies the agent produces valid reports.

This is useful for:
- Regression testing after changes
- Validating research quality
- Benchmarking agent performance

Prerequisites:
    1. Set PARALLEL_API_KEY
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

from agent import research_topic  # noqa: E402

# ============================================================================
# Test Cases
# ============================================================================
TEST_CASES = [
    {
        "name": "quick_research",
        "question": "What is retrieval augmented generation (RAG)?",
        "depth": "quick",
        "expected_in_summary": ["retrieval", "generation"],
        "min_sources": 1,
    },
]


# ============================================================================
# Evaluation Functions
# ============================================================================
def run_test(test_case: dict, verbose: bool = True) -> dict[str, Any]:
    """Run a single test case and check results."""
    name = test_case["name"]
    question = test_case["question"]
    depth = test_case["depth"]

    if verbose:
        print(f"\n  Testing: {name}")
        print(f"  Question: {question}")
        print(f"  Depth: {depth}")

    try:
        # Run research
        report = research_topic(question, depth=depth)

        # Check summary contains expected content
        summary_text = report.summary.lower()
        found = []
        missing = []
        for expected in test_case["expected_in_summary"]:
            if expected.lower() in summary_text:
                found.append(expected)
            else:
                missing.append(expected)

        # Check minimum sources
        num_sources = len(report.sources) if report.sources else 0
        has_enough_sources = num_sources >= test_case["min_sources"]

        # Determine pass/fail
        passed = len(missing) == 0 and has_enough_sources

        if verbose:
            if passed:
                print("  [PASS]")
                print(f"    Summary length: {len(report.summary)} chars")
                print(f"    Key findings: {len(report.key_findings)}")
                print(f"    Sources: {num_sources}")
            else:
                print("  [FAIL]")
                if missing:
                    print(f"    Missing in summary: {missing}")
                if not has_enough_sources:
                    print(
                        f"    Not enough sources: {num_sources} < {test_case['min_sources']}"
                    )

        return {
            "name": name,
            "passed": passed,
            "summary_length": len(report.summary),
            "num_findings": len(report.key_findings),
            "num_sources": num_sources,
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
        print("Research Agent - Evaluation")
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
    print("Research Agent - Evaluation Suite")
    print("=" * 60)
    print(
        """
This script runs research queries to verify agent accuracy.

Each test checks:
  - Summary contains expected keywords
  - Minimum number of sources found
  - Report structure is valid

Note: Requires PARALLEL_API_KEY for web search.
"""
    )

    summary = run_evaluation(verbose=True)

    # Exit with appropriate code
    sys.exit(0 if summary["failed"] == 0 else 1)
