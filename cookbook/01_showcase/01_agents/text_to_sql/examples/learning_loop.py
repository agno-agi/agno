"""
Learning Loop
=============

Demonstrates saving validated queries and reusing them for similar questions.

Usage:
    python scripts/learning_loop.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import sql_agent

MESSAGES = [
    "How many races did each world champion win in their championship year? Show me the last 10 champions.",
    "Yes, please save this query to the knowledge base",
    "Show me the race win count for the 2010-2015 world champions",
]

if __name__ == "__main__":
    for message in MESSAGES:
        print(f"\n> {message}\n")
        sql_agent.print_response(message, stream=True)
        print()
