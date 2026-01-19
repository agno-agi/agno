"""
Summarize Email Thread
======================

Summarize a conversation thread and extract action items.
Demonstrates thread retrieval and analysis.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/inbox_agent/examples/02_summarize_thread.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import inbox_agent  # noqa: E402

# ============================================================================
# Thread Summary Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Summarize Email Thread")
    print("=" * 60)
    print()
    print("This example will:")
    print("1. Find a recent email thread")
    print("2. Retrieve the full conversation")
    print("3. Summarize key points")
    print("4. Extract action items")
    print()
    print("-" * 60)
    print()

    inbox_agent.print_response(
        """Find my most recent email thread with multiple messages and summarize it.

Include:
1. Who is in the conversation
2. What the main topic is
3. Key points discussed
4. Any decisions made
5. Action items (who needs to do what)
6. Any open questions that need resolution""",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Example with specific search
    print("Searching for project-related threads...")
    print("-" * 60)
    print()

    inbox_agent.print_response(
        """Search for emails containing "project" or "meeting" in the last week.
Find the most active thread and summarize the conversation.""",
        stream=True,
    )

    # Uncomment for interactive mode
    # inbox_agent.cli(stream=True)
