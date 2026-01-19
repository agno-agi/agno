"""
Basic SQL Queries
=================

Demonstrates basic Text-to-SQL generation with the SQL agent.

This example shows:
- Simple aggregation queries (counts, sums)
- Filtering by year or driver
- Top-N queries with ordering
- How the agent uses the semantic model to find relevant tables

Example prompts to try:
- "Who won the most races in 2019?"
- "List the top 5 drivers by championship wins"
- "What teams competed in 2020?"

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load F1 data: python scripts/load_f1_data.py
    3. Load knowledge: python scripts/load_knowledge.py

    Or run: python scripts/check_setup.py

Usage:
    python scripts/basic_queries.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import sql_agent  # noqa: E402

# ============================================================================
# Example Queries
# ============================================================================
QUERIES = [
    {
        "title": "Simple Aggregation",
        "description": "Count race wins by driver for a specific year",
        "question": "Who won the most races in 2019?",
    },
    {
        "title": "Top-N Query",
        "description": "Rank drivers by championship wins (handles TEXT position type)",
        "question": "List the top 5 drivers with the most championship wins in F1 history",
    },
    {
        "title": "Filtering Query",
        "description": "List teams for a specific year",
        "question": "What teams competed in the 2020 constructors championship?",
    },
]


def run_query(query: dict, index: int) -> None:
    """Run a single example query."""
    print("=" * 60)
    print(f"Query {index}: {query['title']}")
    print(f"Description: {query['description']}")
    print("=" * 60)
    print(f"\nQuestion: {query['question']}\n")

    sql_agent.print_response(query["question"], stream=True)
    print("\n")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Text-to-SQL Agent - Basic Queries")
    print("=" * 60)
    print("\nThis example demonstrates basic query generation.\n")

    for i, query in enumerate(QUERIES, 1):
        run_query(query, i)

    # Offer interactive mode
    print("=" * 60)
    print("Interactive Mode")
    print("=" * 60)
    print("\nWant to try your own queries? Uncomment the line below or run:")
    print("  sql_agent.cli(stream=True)")
    print()

    # Uncomment for interactive mode:
    # sql_agent.cli(stream=True)
