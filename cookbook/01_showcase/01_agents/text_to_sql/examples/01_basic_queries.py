"""
Basic SQL Queries
=================

Demonstrates basic Text-to-SQL generation with the SQL agent.

This example shows:
- Simple aggregation queries (counts, sums)
- Filtering by year or driver
- Using the semantic model to find relevant tables

Example prompts:
- "Who won the most races in 2019?"
- "List the top 5 drivers by championship wins"
- "What teams competed in 2020?"

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load F1 data: python scripts/load_f1_data.py
    3. Load knowledge: python scripts/load_knowledge.py

Usage:
    python examples/01_basic_queries.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import sql_agent  # noqa: E402

# ============================================================================
# Basic Queries
# ============================================================================
if __name__ == "__main__":
    # Query 1: Simple aggregation
    print("=" * 60)
    print("Query 1: Who won the most races in 2019?")
    print("=" * 60)
    sql_agent.print_response(
        "Who won the most races in 2019?",
        stream=True,
    )

    print("\n")

    # Query 2: Top-N query
    print("=" * 60)
    print("Query 2: List the top 5 drivers with most championship wins")
    print("=" * 60)
    sql_agent.print_response(
        "List the top 5 drivers with the most championship wins in F1 history",
        stream=True,
    )

    print("\n")

    # Query 3: Filtering query
    print("=" * 60)
    print("Query 3: What teams competed in the 2020 constructors championship?")
    print("=" * 60)
    sql_agent.print_response(
        "What teams competed in the 2020 constructors championship?",
        stream=True,
    )

    # Interactive mode (uncomment to use)
    # sql_agent.cli(stream=True)
