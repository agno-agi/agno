"""
Triage Inbox
============

Categorize and prioritize unread emails in your inbox.
Demonstrates email retrieval and intelligent categorization.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/inbox_agent/examples/triage_inbox.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import inbox_agent  # noqa: E402

# ============================================================================
# Triage Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Inbox Triage")
    print("=" * 60)
    print()
    print("This example will:")
    print("1. Retrieve your 10 most recent unread emails")
    print("2. Categorize each email (urgent, action_required, fyi, newsletter)")
    print("3. Assign priorities (1-5)")
    print("4. Provide an executive summary")
    print()
    print("-" * 60)
    print()

    inbox_agent.print_response(
        """Triage my 10 most recent unread emails.

For each email:
1. Categorize it (urgent, action_required, fyi, newsletter, or spam)
2. Assign a priority (1-5, where 1 is most urgent)
3. Write a 1-sentence summary
4. Note any action items

Then provide an executive summary of my inbox status.""",
        stream=True,
    )

    # Uncomment for interactive mode
    # inbox_agent.cli(stream=True)
