"""
Self-Learning Loop
==================

Demonstrates the agent's ability to save validated queries to its knowledge base
and reuse them for future questions.

This is the key differentiator of a self-learning agent:
1. User asks a question
2. Agent generates and executes SQL
3. Agent validates results and asks to save
4. User confirms, agent saves query with metadata
5. Future similar questions retrieve and adapt the saved pattern

What you'll see:
- Query generation with data quality handling
- The save_validated_query tool in action
- Knowledge retrieval for similar questions
- How saved patterns improve consistency

Prerequisites:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load F1 data: python scripts/load_f1_data.py
    3. Load knowledge: python scripts/load_knowledge.py

    Or run: python scripts/check_setup.py

Usage:
    python examples/learning_loop.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import sql_agent  # noqa: E402

# ============================================================================
# Learning Loop Steps
# ============================================================================
STEPS = [
    {
        "step": 1,
        "title": "Initial Question",
        "description": "Ask a complex question requiring a multi-table join",
        "message": (
            "How many races did each world champion win in their championship year? "
            "Show me the last 10 champions."
        ),
        "note": (
            "Watch how the agent:\n"
            "  1. Searches the knowledge base first\n"
            "  2. Handles the TEXT position type in drivers_championship\n"
            "  3. Parses dates in race_wins using TO_DATE\n"
            "  4. Offers to save the query after success"
        ),
    },
    {
        "step": 2,
        "title": "Save the Query",
        "description": "User confirms saving the validated query",
        "message": "Yes, please save this query to the knowledge base",
        "note": (
            "The agent will save:\n"
            "  - Query name and description\n"
            "  - Original question\n"
            "  - SQL query\n"
            "  - Data quality notes (how it handled type issues)"
        ),
    },
    {
        "step": 3,
        "title": "Test Knowledge Retrieval",
        "description": "Ask a similar question to verify saved knowledge is used",
        "message": "Show me the race win count for the 2010-2015 world champions",
        "note": (
            "The agent should:\n"
            "  1. Find the saved query in knowledge search\n"
            "  2. Adapt the pattern for the new date range\n"
            "  3. Generate consistent SQL using the learned pattern"
        ),
    },
]


def run_step(step: dict) -> None:
    """Run a single learning loop step."""
    print("=" * 60)
    print(f"Step {step['step']}: {step['title']}")
    print("=" * 60)
    print(f"\nDescription: {step['description']}")
    print(f'\nMessage: "{step["message"]}"')

    if step.get("note"):
        print(f"\n{step['note']}")

    print("\n" + "-" * 40 + "\n")

    sql_agent.print_response(step["message"], stream=True)
    print("\n")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Text-to-SQL Agent - Self-Learning Loop")
    print("=" * 60)
    print(
        """
This example demonstrates how the agent learns from validated queries.

The learning workflow:
  1. Ask a question → Agent generates SQL
  2. Validate results → Agent offers to save
  3. Confirm save → Query stored with metadata
  4. Ask similar question → Agent retrieves and adapts pattern

This creates a feedback loop where the agent improves over time.
"""
    )

    input("Press Enter to start...\n")

    for step in STEPS:
        run_step(step)
        if step["step"] < len(STEPS):
            input(f"Press Enter for Step {step['step'] + 1}...\n")

    print("=" * 60)
    print("Learning Loop Complete")
    print("=" * 60)
    print(
        """
What happened:
  1. Agent generated a complex multi-table join query
  2. Query was saved with metadata to the knowledge base
  3. Similar question retrieved the saved pattern

The saved query is now part of the agent's knowledge and will be
retrieved for future similar questions, ensuring consistency.

Try running this again - the agent should find the saved query faster!
"""
    )

    # Uncomment for interactive mode:
    # sql_agent.cli(stream=True)
