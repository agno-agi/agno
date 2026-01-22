"""
Create Linear Issue
===================

Create issues from natural language descriptions.
Demonstrates issue creation with automatic field extraction.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/linear_agent/examples/create_issue.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import linear_agent  # noqa: E402

# ============================================================================
# Create Issue Examples
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Create Linear Issue")
    print("=" * 60)
    print()
    print("This example will:")
    print("1. Get available teams")
    print("2. Parse natural language to extract issue details")
    print("3. Create the issue in Linear")
    print()
    print("-" * 60)
    print()

    # First, get teams to understand the workspace
    print("Getting available teams...")
    print("-" * 40)
    linear_agent.print_response(
        "What teams are available in Linear?",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Create a bug report
    print("Creating a bug report...")
    print("-" * 40)
    linear_agent.print_response(
        """Create a bug: The login button on the homepage is not responding when clicked.
This is high priority as users can't log in.
Steps to reproduce:
1. Go to homepage
2. Click the login button
3. Nothing happens

Expected: Login modal should appear""",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Create a feature request
    print("Creating a feature request...")
    print("-" * 40)
    linear_agent.print_response(
        """Create a feature request: Add dark mode support to the dashboard.
Users have been asking for this. Nice to have, not urgent.""",
        stream=True,
    )

    # Uncomment for interactive mode
    # linear_agent.cli(stream=True)
