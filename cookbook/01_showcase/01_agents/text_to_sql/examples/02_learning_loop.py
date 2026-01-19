"""
Self-Learning Loop
==================

Demonstrates the agent's ability to save validated queries to its knowledge base
and reuse them for future questions.

This example shows:
- Query execution and validation
- Saving queries to the knowledge base
- How saved queries improve future responses

The learning workflow:
1. User asks a question
2. Agent generates and executes SQL
3. Agent asks if user wants to save the query
4. If saved, the query becomes part of the agent's knowledge
5. Future similar questions benefit from the saved pattern

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load F1 data: python scripts/load_f1_data.py
    3. Load knowledge: python scripts/load_knowledge.py

Usage:
    python examples/02_learning_loop.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import sql_agent  # noqa: E402

# ============================================================================
# Learning Loop Demonstration
# ============================================================================
if __name__ == "__main__":
    # Step 1: Ask a question that requires a complex query
    print("=" * 60)
    print("Step 1: Initial Question")
    print("=" * 60)
    print(
        "Asking: 'How many races did each world champion win in their championship year?'"
    )
    print()

    sql_agent.print_response(
        "How many races did each world champion win in their championship year? "
        "Show me the last 10 champions.",
        stream=True,
    )

    print("\n")

    # Step 2: Simulate user confirming to save
    print("=" * 60)
    print("Step 2: Saving the Query")
    print("=" * 60)
    print("User confirms: 'Yes, please save this query'")
    print()

    sql_agent.print_response(
        "Yes, please save this query to the knowledge base",
        stream=True,
    )

    print("\n")

    # Step 3: Ask a similar question to see if it uses saved knowledge
    print("=" * 60)
    print("Step 3: Testing Knowledge Retrieval")
    print("=" * 60)
    print("Asking a similar question to test if saved knowledge is used...")
    print()

    sql_agent.print_response(
        "Show me the race win count for the 2010-2015 world champions",
        stream=True,
    )

    # Interactive mode for further exploration (uncomment to use)
    # sql_agent.cli(stream=True)
