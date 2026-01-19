"""
Load Knowledge
==============

Loads table metadata and query patterns into the agent's knowledge base.

Usage:
    python scripts/load_knowledge.py
"""

import sys
from pathlib import Path

_parent = Path(__file__).parent.parent
sys.path.insert(0, str(_parent))

KNOWLEDGE_DIR = _parent / "knowledge"


def load_knowledge() -> bool:
    """Load knowledge files into the SQL agent's knowledge base."""
    from agent import sql_agent_knowledge

    try:
        sql_agent_knowledge.insert(name="SQL Agent Knowledge", path=str(KNOWLEDGE_DIR))
        print("Knowledge loaded successfully")
        return True
    except Exception as e:
        print(f"Failed to load knowledge: {e}")
        return False


if __name__ == "__main__":
    sys.exit(0 if load_knowledge() else 1)
