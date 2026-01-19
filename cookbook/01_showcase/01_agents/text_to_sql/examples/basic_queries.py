"""
Basic Queries
=============

Usage:
    python scripts/basic_queries.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import sql_agent

QUERIES = [
    "Who won the most races in 2019?",
    "List the top 5 drivers with the most championship wins in F1 history",
    "What teams competed in the 2020 constructors championship?",
]

if __name__ == "__main__":
    for query in QUERIES:
        print(f"\n> {query}\n")
        sql_agent.print_response(query, stream=True)
        print()
