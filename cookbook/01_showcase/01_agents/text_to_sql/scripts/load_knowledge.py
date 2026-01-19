"""
Load SQL Agent Knowledge
========================

Loads table metadata, query patterns, and sample queries from the knowledge
directory into the agent's knowledge base.

Knowledge files loaded:
- Table schemas (JSON): Column descriptions, types, data quality notes
- Sample queries (SQL): Validated query patterns with explanations

Usage:
    python scripts/load_knowledge.py

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Set OPENAI_API_KEY for embeddings
"""

import os
import sys
from pathlib import Path
from agno.utils.log import logger

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

# ============================================================================
# Configuration
# ============================================================================
KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"


# ============================================================================
# Validation
# ============================================================================
def check_prerequisites() -> bool:
    """Check prerequisites before loading knowledge."""
    # Check OPENAI_API_KEY
    if not os.environ.get("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY not set (required for embeddings)")
        logger.error("Run: export OPENAI_API_KEY=your-key")
        return False

    # Check knowledge directory exists
    if not KNOWLEDGE_DIR.exists():
        logger.error(f"Knowledge directory not found: {KNOWLEDGE_DIR}")
        return False

    # Check for knowledge files
    files = list(KNOWLEDGE_DIR.iterdir())
    if not files:
        logger.error(f"No files found in {KNOWLEDGE_DIR}")
        return False

    return True


# ============================================================================
# Knowledge Loading
# ============================================================================
def load_knowledge() -> bool:
    """Load knowledge files into the SQL agent's knowledge base.

    Returns:
        bool: True if knowledge loaded successfully, False otherwise.
    """
    # Check prerequisites first
    if not check_prerequisites():
        return False

    # Import here to avoid errors if prerequisites fail
    try:
        from agent import sql_agent_knowledge
    except ImportError as e:
        logger.error(f"Failed to import agent: {e}")
        logger.error("Make sure you're running from the text_to_sql directory")
        return False
    except Exception as e:
        logger.error(f"Failed to initialize agent: {e}")
        logger.error("Check database connection and API keys")
        return False

    logger.info(f"Loading SQL Agent Knowledge from {KNOWLEDGE_DIR}")
    logger.info("")

    # List files being loaded
    file_count = 0
    for f in sorted(KNOWLEDGE_DIR.iterdir()):
        if f.is_file():
            suffix = f.suffix.lower()
            file_type = {
                ".json": "table schema",
                ".sql": "query patterns",
            }.get(suffix, "document")
            logger.info(f"  {f.name} ({file_type})")
            file_count += 1

    logger.info("")

    if file_count == 0:
        logger.error("No knowledge files found")
        return False

    # Load all files in the knowledge directory
    try:
        sql_agent_knowledge.add_content(path=str(KNOWLEDGE_DIR))
        logger.info(f"✓ Loaded {file_count} knowledge files successfully")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to load knowledge: {e}")
        return False


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    success = load_knowledge()
    sys.exit(0 if success else 1)
