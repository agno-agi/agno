"""
Draft Email Response
====================

Draft contextual responses to emails.
Demonstrates intelligent response drafting (does NOT send without approval).

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/inbox_agent/examples/draft_response.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import inbox_agent  # noqa: E402

# ============================================================================
# Draft Response Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Draft Email Response")
    print("=" * 60)
    print()
    print("This example will:")
    print("1. Find an email that needs a response")
    print("2. Analyze the context and tone")
    print("3. Draft an appropriate response")
    print("4. Save as a draft (NOT send)")
    print()
    print("NOTE: The agent will NOT send any emails without explicit approval.")
    print()
    print("-" * 60)
    print()

    inbox_agent.print_response(
        """Find my most recent email that asks a question or requests something.
Then:
1. Summarize what they're asking
2. Draft a professional response
3. Create it as a draft email (do NOT send it)
4. Explain what you drafted and why you chose that approach""",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Example with specific tone
    print("Drafting with specific tone...")
    print("-" * 60)
    print()

    inbox_agent.print_response(
        """Look at my latest unread email.
Draft a friendly but professional response.
Create it as a draft so I can review before sending.""",
        stream=True,
    )

    # Uncomment for interactive mode
    # inbox_agent.cli(stream=True)
