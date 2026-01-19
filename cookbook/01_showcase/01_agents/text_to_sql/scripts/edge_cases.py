"""
Edge Cases and Data Quality
===========================

Demonstrates the agent handling complex queries with real-world data quality issues.

This example shows:
- Multi-table joins with different column types
- Date parsing from TEXT columns
- Handling non-numeric position values ('Ret', 'DSQ', 'DNS')
- Ambiguous requests requiring interpretation
- Column name inconsistencies (driver_tag vs name_tag)

Key data quality issues in this dataset:
- position: INTEGER in constructors_championship, TEXT in others
- date: TEXT format 'DD Mon YYYY' in race_wins (no year column)
- position values: '1', '2', 'Ret', 'DSQ', 'DNS', 'NC' in race_results
- driver tags: 'driver_tag' in some tables, 'name_tag' in others

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load F1 data: python scripts/load_f1_data.py
    3. Load knowledge: python scripts/load_knowledge.py

    Or run: python scripts/check_setup.py

Usage:
    python scripts/edge_cases.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import sql_agent  # noqa: E402

# ============================================================================
# Edge Case Queries
# ============================================================================
QUERIES = [
    {
        "title": "Multi-table Join with Type Mismatch",
        "description": "Joins constructors_championship (INT position) with race_wins (TEXT date)",
        "question": (
            "Compare the number of race wins vs championship positions for constructors in 2019. "
            "Which team outperformed their championship position based on wins?"
        ),
        "data_quality_note": (
            "This query must handle:\n"
            "  - position as INTEGER in constructors_championship\n"
            "  - date as TEXT in race_wins requiring TO_DATE parsing"
        ),
    },
    {
        "title": "Time-Series with Date Parsing",
        "description": "Aggregates points across years, joining on team names",
        "question": (
            "Compare Ferrari vs Mercedes constructor championship points from 2015 to 2020. "
            "Show the year-by-year breakdown."
        ),
        "data_quality_note": (
            "Team names must match exactly across tables.\n"
            "Points aggregation from constructors_championship."
        ),
    },
    {
        "title": "Venue-based Query with Column Name Inconsistency",
        "description": "Uses fastest_laps table which has driver_tag (not name_tag)",
        "question": "Who has set the most fastest laps at Monaco? Show the top 5 drivers.",
        "data_quality_note": (
            "fastest_laps uses 'driver_tag' column.\n"
            "race_wins and race_results use 'name_tag' instead."
        ),
    },
    {
        "title": "Handling Non-Numeric Positions",
        "description": "Counts retirements which have position='Ret' (TEXT, not numeric)",
        "question": "Which driver had the most retirements in 2020?",
        "data_quality_note": (
            "race_results.position is TEXT and contains:\n"
            "  - Numeric positions: '1', '2', '3', ...\n"
            "  - Non-finishes: 'Ret', 'DSQ', 'DNS', 'NC'"
        ),
    },
    {
        "title": "Ambiguous Request",
        "description": "Requires interpretation - what does 'most successful' mean?",
        "question": (
            "Who is the most successful F1 driver of all time? "
            "Consider championships, race wins, and other statistics."
        ),
        "data_quality_note": (
            "This is intentionally ambiguous. Watch how the agent:\n"
            "  - Interprets 'success' (championships? wins? points?)\n"
            "  - Combines data from multiple tables\n"
            "  - Handles the TEXT position type for championship counts"
        ),
    },
]


def run_query(query: dict, index: int) -> None:
    """Run a single edge case query."""
    print("=" * 60)
    print(f"Query {index}: {query['title']}")
    print("=" * 60)
    print(f"\nDescription: {query['description']}")
    print(f"\nData Quality Notes:\n{query['data_quality_note']}")
    print(f"\nQuestion: {query['question']}")
    print("\n" + "-" * 40 + "\n")

    sql_agent.print_response(query["question"], stream=True)
    print("\n")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Text-to-SQL Agent - Edge Cases & Data Quality")
    print("=" * 60)
    print(
        """
This example demonstrates handling real-world data quality issues.

The F1 dataset has intentional inconsistencies that mirror real data:
  - Mixed types: position is INT in one table, TEXT in others
  - Date formats: TEXT 'DD Mon YYYY' requiring parsing
  - Non-numeric values: 'Ret', 'DSQ', 'DNS' in position columns
  - Column naming: 'driver_tag' vs 'name_tag' across tables

Watch how the agent uses knowledge base patterns to handle these issues
consistently without requiring data cleanup.
"""
    )

    for i, query in enumerate(QUERIES, 1):
        run_query(query, i)
        if i < len(QUERIES):
            print("(Press Ctrl+C to exit early)\n")

    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(
        """
Key takeaways:
  1. The agent handles data quality issues through knowledge, not data fixes
  2. Pattern retrieval ensures consistent SQL generation
  3. Data quality notes in knowledge files guide correct type handling
  4. Ambiguous queries are interpreted reasonably with explanations

This approach scales better than cleaning data because:
  - New data quality issues can be documented without ETL changes
  - The agent learns and improves over time
  - Patterns are reusable across similar questions
"""
    )

    # Uncomment for interactive mode:
    # sql_agent.cli(stream=True)
