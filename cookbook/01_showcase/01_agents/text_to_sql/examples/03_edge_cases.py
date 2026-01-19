"""
Edge Cases and Complex Queries
==============================

Demonstrates the agent handling complex queries that require:
- Multi-table joins
- Subqueries and CTEs
- Date parsing and extraction
- Handling ambiguous requests

This example shows:
- Joining across multiple tables
- Complex aggregations
- Time-series analysis
- Handling edge cases gracefully

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load F1 data: python scripts/load_f1_data.py
    3. Load knowledge: python scripts/load_knowledge.py

Usage:
    python examples/03_edge_cases.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import sql_agent  # noqa: E402

# ============================================================================
# Complex Query Examples
# ============================================================================
if __name__ == "__main__":
    # Query 1: Multi-table join
    print("=" * 60)
    print("Query 1: Multi-table Join")
    print("Compare constructor championship positions vs race wins")
    print("=" * 60)
    sql_agent.print_response(
        "Compare the number of race wins vs championship positions for constructors in 2019. "
        "Which team outperformed their championship position based on wins?",
        stream=True,
    )

    print("\n")

    # Query 2: Time-series analysis
    print("=" * 60)
    print("Query 2: Time-Series Analysis")
    print("Ferrari vs Mercedes performance over time")
    print("=" * 60)
    sql_agent.print_response(
        "Compare Ferrari vs Mercedes constructor championship points from 2015 to 2020. "
        "Show the year-by-year breakdown.",
        stream=True,
    )

    print("\n")

    # Query 3: Complex aggregation with date parsing
    print("=" * 60)
    print("Query 3: Date Parsing and Aggregation")
    print("Fastest laps at Monaco Grand Prix")
    print("=" * 60)
    sql_agent.print_response(
        "Who has set the most fastest laps at Monaco? Show the top 5 drivers.",
        stream=True,
    )

    print("\n")

    # Query 4: Handling ambiguity
    print("=" * 60)
    print("Query 4: Handling Ambiguous Requests")
    print("Best driver - requires interpretation")
    print("=" * 60)
    sql_agent.print_response(
        "Who is the most successful F1 driver of all time? "
        "Consider championships, race wins, and other statistics.",
        stream=True,
    )

    # Interactive mode for further exploration (uncomment to use)
    # sql_agent.cli(stream=True)
