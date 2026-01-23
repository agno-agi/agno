"""
Basic Document Summary
======================

Demonstrates basic document summarization with the Document Summarizer agent.

This example shows:
- Summarizing a text file
- Accessing structured summary fields
- Displaying key points and entities

Usage:
    python examples/basic_summary.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import summarize_document  # noqa: E402

# ============================================================================
# Basic Summary Example
# ============================================================================
if __name__ == "__main__":
    # Path to sample document
    doc_path = Path(__file__).parent.parent / "documents" / "meeting_notes.txt"

    print("=" * 60)
    print("Document Summarizer - Basic Example")
    print("=" * 60)
    print(f"Summarizing: {doc_path.name}")
    print()

    try:
        # Summarize the document
        summary = summarize_document(str(doc_path))

        # Display results
        print("TITLE:", summary.title)
        print("TYPE:", summary.document_type)
        print("CONFIDENCE:", f"{summary.confidence:.0%}")
        print()

        print("SUMMARY:")
        print("-" * 40)
        print(summary.summary)
        print()

        print("KEY POINTS:")
        print("-" * 40)
        for i, point in enumerate(summary.key_points, 1):
            print(f"  {i}. {point}")
        print()

        if summary.entities:
            print("ENTITIES:")
            print("-" * 40)
            for entity in summary.entities:
                context = f" - {entity.context}" if entity.context else ""
                print(f"  [{entity.type}] {entity.name}{context}")
            print()

        if summary.action_items:
            print("ACTION ITEMS:")
            print("-" * 40)
            for item in summary.action_items:
                owner = f" ({item.owner})" if item.owner else ""
                deadline = f" - Due: {item.deadline}" if item.deadline else ""
                priority = f" [{item.priority}]" if item.priority else ""
                print(f"  - {item.task}{owner}{deadline}{priority}")

    except Exception as e:
        print(f"Error: {e}")
