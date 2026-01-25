"""
Entity Extraction Focus
=======================

Demonstrates entity extraction capabilities of the Document Summarizer.

This example shows:
- Extracting entities from a technical blog post
- Categorizing entities by type
- Using entity context for additional information

Usage:
    python examples/extract_entities.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import summarize_document  # noqa: E402

# ============================================================================
# Entity Extraction Example
# ============================================================================
if __name__ == "__main__":
    # Path to sample document
    doc_path = Path(__file__).parent.parent / "documents" / "blog_post.md"

    print("=" * 60)
    print("Document Summarizer - Entity Extraction")
    print("=" * 60)
    print(f"Analyzing: {doc_path.name}")
    print()

    try:
        # Summarize the document
        summary = summarize_document(str(doc_path))

        print("DOCUMENT:", summary.title)
        print("TYPE:", summary.document_type)
        print()

        # Group entities by type
        entities_by_type: dict[str, list] = {}
        for entity in summary.entities:
            if entity.type not in entities_by_type:
                entities_by_type[entity.type] = []
            entities_by_type[entity.type].append(entity)

        print("ENTITIES BY TYPE:")
        print("-" * 40)

        for entity_type, entities in sorted(entities_by_type.items()):
            print(f"\n{entity_type.upper()} ({len(entities)}):")
            for entity in entities:
                if entity.context:
                    print(f"  - {entity.name}")
                    print(f"    Context: {entity.context}")
                else:
                    print(f"  - {entity.name}")

        print()
        print("SUMMARY:")
        print("-" * 40)
        print(summary.summary)

    except Exception as e:
        print(f"Error: {e}")
