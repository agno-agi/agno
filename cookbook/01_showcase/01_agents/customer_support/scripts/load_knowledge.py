"""
Load Knowledge Documents
========================

Script to load support documentation into the knowledge base.
Includes production-level ticket management guides and Agno documentation.

Usage:
    # Start PostgreSQL first
    ./cookbook/scripts/run_pgvector.sh

    # Load knowledge documents
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/scripts/load_knowledge.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import KNOWLEDGE_DIR, support_knowledge  # noqa: E402

# ============================================================================
# Agno Documentation URLs
# ============================================================================
AGNO_DOCS = [
    "https://docs.agno.com/introduction",
    "https://docs.agno.com/agents/introduction",
    "https://docs.agno.com/agents/knowledge",
    "https://docs.agno.com/agents/memory",
    "https://docs.agno.com/agents/tools",
    "https://docs.agno.com/teams/introduction",
    "https://docs.agno.com/vectordb/introduction",
    "https://docs.agno.com/vectordb/pgvector",
]


# ============================================================================
# Load Functions
# ============================================================================
def load_local_knowledge():
    """Load local markdown files into the knowledge base."""
    print("Loading local support documentation...")
    print(f"Directory: {KNOWLEDGE_DIR}")
    print()

    md_files = list(KNOWLEDGE_DIR.glob("*.md"))

    if not md_files:
        print("No markdown files found.")
        return 0

    print(f"Found {len(md_files)} documentation files:")
    for f in md_files:
        print(f"  - {f.name}")
    print()

    # Load all local docs
    print("Loading into knowledge base...")
    try:
        support_knowledge.load(path=str(KNOWLEDGE_DIR))
        print(f"  Loaded {len(md_files)} files")
        return len(md_files)
    except Exception as e:
        print(f"  FAILED: {e}")
        return 0


def load_agno_docs():
    """Load Agno documentation from public URLs."""
    print()
    print("Loading Agno documentation from docs.agno.com...")
    print()

    loaded = 0
    failed = 0

    for url in AGNO_DOCS:
        try:
            print(f"  Loading: {url}")
            support_knowledge.load(url=url)
            loaded += 1
        except Exception as e:
            failed += 1
            print(f"    FAILED: {e}")

    print()
    print(f"Loaded {loaded}/{loaded + failed} Agno docs")
    return loaded


# ============================================================================
# Main
# ============================================================================
def main():
    print("=" * 60)
    print("Customer Support Agent - Load Knowledge Base")
    print("=" * 60)
    print()

    total_loaded = 0

    # Load local production documentation first (these always work)
    local_count = load_local_knowledge()
    total_loaded += local_count

    # Load Agno docs from URLs
    agno_count = load_agno_docs()
    total_loaded += agno_count

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Local docs loaded: {local_count}")
    print(f"  Agno docs loaded:  {agno_count}")
    print(f"  Total documents:   {total_loaded}")
    print()

    if total_loaded > 0:
        print("Knowledge base ready!")
        print()
        print("The agent now has access to:")
        print("  - Ticket triage best practices")
        print("  - Escalation guidelines")
        print("  - Response templates with empathy statements")
        print("  - SLA guidelines")
        print("  - Agno product documentation")
        print()
        print("Run the examples:")
        print(
            "  .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/basic_support.py"
        )
    else:
        print("WARNING: No documents loaded. Check the errors above.")


if __name__ == "__main__":
    main()
