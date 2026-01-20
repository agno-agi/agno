"""
Batch Document Processing
=========================

Demonstrates processing multiple documents with the Document Summarizer.

This example shows:
- Processing multiple documents in sequence
- Comparing summaries across documents
- Handling errors gracefully

Usage:
    python examples/batch_processing.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import summarize_document  # noqa: E402
from schemas import DocumentSummary  # noqa: E402

# ============================================================================
# Batch Processing Example
# ============================================================================
if __name__ == "__main__":
    # Find all documents in the documents folder
    docs_dir = Path(__file__).parent.parent / "documents"
    documents = list(docs_dir.glob("*"))
    documents = [d for d in documents if d.suffix in {".txt", ".md", ".pdf"}]

    print("=" * 60)
    print("Document Summarizer - Batch Processing")
    print("=" * 60)
    print(f"Found {len(documents)} documents to process")
    print()

    results: list[tuple[str, DocumentSummary | str]] = []

    for i, doc_path in enumerate(documents, 1):
        print(f"[{i}/{len(documents)}] Processing: {doc_path.name}")

        try:
            summary = summarize_document(str(doc_path))
            results.append((doc_path.name, summary))
            print(f"    Type: {summary.document_type}")
            print(f"    Confidence: {summary.confidence:.0%}")
            print(f"    Key Points: {len(summary.key_points)}")
            print(f"    Entities: {len(summary.entities)}")
            print(f"    Action Items: {len(summary.action_items)}")
        except Exception as e:
            results.append((doc_path.name, str(e)))
            print(f"    Error: {e}")

        print()

    # Summary comparison
    print("=" * 60)
    print("BATCH SUMMARY")
    print("=" * 60)
    print()

    successful = [r for r in results if isinstance(r[1], DocumentSummary)]
    failed = [r for r in results if isinstance(r[1], str)]

    print(f"Processed: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print()

    if successful:
        print("DOCUMENT COMPARISON:")
        print("-" * 60)
        print(f"{'Document':<30} {'Type':<15} {'Confidence':<12} {'Actions':<8}")
        print("-" * 60)

        for name, summary in successful:
            if isinstance(summary, DocumentSummary):
                print(
                    f"{name:<30} {summary.document_type:<15} "
                    f"{summary.confidence:<12.0%} {len(summary.action_items):<8}"
                )

    if failed:
        print()
        print("FAILED DOCUMENTS:")
        for name, error in failed:
            print(f"  - {name}: {error}")
