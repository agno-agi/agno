"""
Load SQL Agent Knowledge
========================

Loads table metadata, query patterns, and sample queries from the knowledge
directory into the agent's knowledge base.

Usage:
    python scripts/load_knowledge.py

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Set OPENAI_API_KEY for embeddings
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import sql_agent_knowledge  # noqa: E402
from agno.utils.log import logger  # noqa: E402

# ============================================================================
# Configuration
# ============================================================================
KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"


# ============================================================================
# Knowledge Loading
# ============================================================================
def load_knowledge() -> None:
    """Load knowledge files into the SQL agent's knowledge base."""
    if not KNOWLEDGE_DIR.exists():
        logger.error(f"Knowledge directory not found: {KNOWLEDGE_DIR}")
        return

    logger.info(f"Loading SQL Agent Knowledge from {KNOWLEDGE_DIR}")

    # List files being loaded
    for f in KNOWLEDGE_DIR.iterdir():
        if f.is_file():
            logger.info(f"  Found: {f.name}")

    # Load all files in the knowledge directory
    sql_agent_knowledge.add_content(path=str(KNOWLEDGE_DIR))

    logger.info("SQL Agent Knowledge loaded successfully.")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    load_knowledge()
