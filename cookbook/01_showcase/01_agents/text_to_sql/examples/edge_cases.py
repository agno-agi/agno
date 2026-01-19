"""
Edge Cases
==========

Queries that test data quality handling (type mismatches, date parsing, etc.)

Usage:
    python scripts/edge_cases.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import sql_agent

QUERIES = [
    "Compare the number of race wins vs championship positions for constructors in 2019. Which team outperformed their championship position based on wins?",
    "Compare Ferrari vs Mercedes constructor championship points from 2015 to 2020. Show the year-by-year breakdown.",
    "Who has set the most fastest laps at Monaco? Show the top 5 drivers.",
    "Which driver had the most retirements in 2020?",
    "Who is the most successful F1 driver of all time? Consider championships, race wins, and other statistics.",
]

if __name__ == "__main__":
    for query in QUERIES:
        print(f"\n> {query}\n")
        sql_agent.print_response(query, stream=True)
        print()
