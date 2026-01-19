"""
Evaluate Agent Accuracy
=======================

Runs a standard set of documents and verifies the agent extracts expected content.

This is useful for:
- Regression testing after changes
- Validating summarization quality
- Benchmarking agent performance

Test cases cover:
- Meeting notes extraction
- Entity identification
- Action item detection
- Key point extraction

Prerequisites:
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

from agent import summarize_document  # noqa: E402

# ============================================================================
# Test Cases
# ============================================================================
TEST_CASES = [
    {
        "name": "meeting_notes_summary",
        "document": "documents/meeting_notes.txt",
        "expected_in_summary": ["Q4", "dashboard", "February", "March"],
        "expected_entities": ["Sarah Chen", "Mike Johnson"],
        "expected_action_items": ["contractor", "HR", "design assets"],
        "document_type": "meeting_notes",
    },
    {
        "name": "blog_post_summary",
        "document": "documents/blog_post.md",
        "expected_in_summary": [],  # Will just check that summary is generated
        "expected_entities": [],
        "expected_action_items": [],
        "document_type": None,  # Any type is acceptable
    },
]


# ============================================================================
# Evaluation Functions
# ============================================================================
def run_test(test_case: dict, verbose: bool = True) -> dict[str, Any]:
    """Run a single test case and check results.

    Args:
        test_case: Test case dictionary with document and expected values
        verbose: Whether to print detailed output

    Returns:
        dict with test results
    """
    name = test_case["name"]
    doc_path = _this_dir / test_case["document"]

    if verbose:
        print(f"\n  Testing: {name}")
        print(f"  Document: {test_case['document']}")

    try:
        # Summarize the document
        summary = summarize_document(str(doc_path))

        # Check summary contains expected content
        summary_text = summary.summary.lower()
        found_in_summary = []
        missing_in_summary = []
        for expected in test_case["expected_in_summary"]:
            if expected.lower() in summary_text:
                found_in_summary.append(expected)
            else:
                missing_in_summary.append(expected)

        # Check entities
        entity_names = (
            [e.name.lower() for e in summary.entities] if summary.entities else []
        )
        found_entities = []
        missing_entities = []
        for expected in test_case["expected_entities"]:
            if any(expected.lower() in name for name in entity_names):
                found_entities.append(expected)
            else:
                missing_entities.append(expected)

        # Check action items
        action_texts = []
        if summary.action_items:
            for item in summary.action_items:
                action_texts.append(item.task.lower())
        found_actions = []
        missing_actions = []
        for expected in test_case["expected_action_items"]:
            if any(expected.lower() in text for text in action_texts):
                found_actions.append(expected)
            else:
                missing_actions.append(expected)

        # Check document type
        type_ok = True
        if test_case["document_type"]:
            type_ok = summary.document_type == test_case["document_type"]

        # Determine pass/fail
        passed = (
            len(missing_in_summary) == 0
            and len(missing_entities) == 0
            and len(missing_actions) == 0
            and type_ok
            and summary.confidence >= 0.5
        )

        if verbose:
            if passed:
                print("  [PASS]")
                print(f"    Summary length: {len(summary.summary)} chars")
                print(f"    Key points: {len(summary.key_points)}")
                print(
                    f"    Entities: {len(summary.entities) if summary.entities else 0}"
                )
                print(
                    f"    Action items: {len(summary.action_items) if summary.action_items else 0}"
                )
                print(f"    Confidence: {summary.confidence:.0%}")
            else:
                print("  [FAIL]")
                if missing_in_summary:
                    print(f"    Missing in summary: {missing_in_summary}")
                if missing_entities:
                    print(f"    Missing entities: {missing_entities}")
                if missing_actions:
                    print(f"    Missing action items: {missing_actions}")
                if not type_ok:
                    print(
                        f"    Wrong type: {summary.document_type} (expected: {test_case['document_type']})"
                    )

        return {
            "name": name,
            "passed": passed,
            "summary_length": len(summary.summary),
            "key_points_count": len(summary.key_points),
            "entities_count": len(summary.entities) if summary.entities else 0,
            "action_items_count": len(summary.action_items)
            if summary.action_items
            else 0,
            "confidence": summary.confidence,
            "missing_in_summary": missing_in_summary,
            "missing_entities": missing_entities,
            "missing_actions": missing_actions,
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
    """Run all test cases and return summary.

    Args:
        verbose: Whether to print detailed output

    Returns:
        dict with evaluation summary
    """
    if verbose:
        print("=" * 60)
        print("Document Summarizer - Evaluation")
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
    print("Document Summarizer - Evaluation Suite")
    print("=" * 60)
    print(
        """
This script runs a set of documents to verify agent accuracy.

Each test checks that expected content appears in the summary:
  - Key terms in summary text
  - Important entities identified
  - Action items extracted
"""
    )

    summary = run_evaluation(verbose=True)

    # Exit with appropriate code
    sys.exit(0 if summary["failed"] == 0 else 1)
