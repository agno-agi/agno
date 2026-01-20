"""
Query Linear Issues
===================

Query issues using natural language.
Demonstrates various query patterns.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/linear_agent/examples/query_issues.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import linear_agent  # noqa: E402

# ============================================================================
# Query Examples
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Query Linear Issues")
    print("=" * 60)
    print()
    print("This example demonstrates various query patterns.")
    print()
    print("-" * 60)
    print()

    # Get current user and their issues
    print("Query 1: My assigned issues")
    print("-" * 40)
    linear_agent.print_response(
        "What issues are assigned to me?",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # High priority issues
    print("Query 2: High priority issues")
    print("-" * 40)
    linear_agent.print_response(
        "Show me all high priority issues that need attention.",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Get issue details
    print("Query 3: Issue details")
    print("-" * 40)
    linear_agent.print_response(
        "Get the details of the most recent high priority issue.",
        stream=True,
    )

    # Uncomment for interactive mode
    # linear_agent.cli(stream=True)
