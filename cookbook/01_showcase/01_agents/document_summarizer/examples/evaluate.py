"""
Evaluate
========

Runs test cases and verifies expected results for the Document Summarizer agent.

Usage:
    python examples/evaluate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import summarize_document  # noqa: E402

# Test documents directory
DOCUMENTS_DIR = Path(__file__).parent.parent / "documents"

TEST_CASES = [
    {
        "file": "blog_post.md",
        "expected_type": "article",
        "expected_keywords": ["AI", "agent", "production"],
        "min_key_points": 3,
    },
    {
        "file": "meeting_notes.txt",
        "expected_type": "meeting_notes",
        "expected_keywords": ["action", "meeting"],
        "min_key_points": 2,
    },
]


def run_evaluation() -> bool:
    passed = 0
    failed = 0

    for test in TEST_CASES:
        file_path = DOCUMENTS_DIR / test["file"]
        print(f"Testing: {test['file']}")

        try:
            summary = summarize_document(str(file_path))

            errors = []

            # Check document type
            if summary.document_type != test["expected_type"]:
                errors.append(
                    f"Expected type '{test['expected_type']}', got '{summary.document_type}'"
                )

            # Check for expected keywords in summary
            summary_lower = summary.summary.lower()
            missing_keywords = [
                kw
                for kw in test["expected_keywords"]
                if kw.lower() not in summary_lower
            ]
            if missing_keywords:
                errors.append(f"Missing keywords in summary: {missing_keywords}")

            # Check minimum key points
            if len(summary.key_points) < test["min_key_points"]:
                errors.append(
                    f"Expected at least {test['min_key_points']} key points, "
                    f"got {len(summary.key_points)}"
                )

            # Check confidence score
            if summary.confidence < 0.5:
                errors.append(f"Low confidence score: {summary.confidence}")

            if errors:
                print("  x FAIL")
                for error in errors:
                    print(f"    - {error}")
                failed += 1
            else:
                print("  v PASS")
                passed += 1

        except Exception as e:
            print(f"  x FAIL - Exception: {e}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_evaluation() else 1)
