"""
Load Knowledge Documents
========================

Script to load company documents into the knowledge base.
Run this before using the knowledge agent.

Usage:
    # Start PostgreSQL first
    ./cookbook/scripts/run_pgvector.sh

    # Load knowledge documents
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/knowledge_agent/scripts/load_knowledge.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import KNOWLEDGE_DIR, company_knowledge  # noqa: E402


# ============================================================================
# Load Documents
# ============================================================================
def load_knowledge_base():
    """Load all documents from the knowledge directory into the knowledge base."""
    print("Loading company knowledge base...")
    print(f"Knowledge directory: {KNOWLEDGE_DIR}")
    print()

    # Find all markdown files in the knowledge directory
    md_files = list(KNOWLEDGE_DIR.glob("*.md"))

    if not md_files:
        print("No markdown files found in knowledge directory.")
        return

    print(f"Found {len(md_files)} documents:")
    for f in md_files:
        print(f"  - {f.name}")
    print()

    # Load each document
    for doc_path in md_files:
        doc_name = doc_path.stem.replace("_", " ").title()
        print(f"Loading: {doc_name}...")
        company_knowledge.load(
            path=str(doc_path),
            recreate=False,
            skip_existing=True,
        )
        print(f"  Loaded: {doc_path.name}")

    print()
    print("Knowledge base loaded successfully.")
    print()
    print("You can now run the examples:")
    print(
        "  .venvs/demo/bin/python cookbook/01_showcase/01_agents/knowledge_agent/examples/01_basic_query.py"
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    load_knowledge_base()
