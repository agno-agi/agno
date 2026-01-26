"""
Process Retrospective Actions
=============================

Extract and track action items from a retrospective meeting.
Demonstrates handling process improvement tasks.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/meeting_tasks_agent/examples/retro_actions.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import MEETINGS_DIR, meeting_tasks_agent, process_meeting_file  # noqa: E402

# ============================================================================
# Retrospective Actions Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Process Retrospective Actions")
    print("=" * 60)
    print()
    print("This example will:")
    print("1. Read the retrospective notes")
    print("2. Extract improvement action items")
    print("3. Categorize by type (process, technical debt, quick wins)")
    print("4. Prepare issues for tracking")
    print()
    print("-" * 60)
    print()

    # Read the retro notes
    retro_file = MEETINGS_DIR / "retro_notes.md"
    meeting_content = process_meeting_file(str(retro_file))

    meeting_tasks_agent.print_response(
        f"""Process this sprint retrospective and extract ALL action items.

Categorize them into:
1. **Process Improvements** - Changes to how we work
2. **Technical Debt** - Code/system improvements
3. **Quick Wins** - Easy items to address soon

For each action item, extract:
- Clear task description
- Owner
- Deadline (if mentioned)
- Priority
- Category

Then summarize:
- Total action items found
- Breakdown by category
- Highest priority items

Retrospective Notes:

{meeting_content}""",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Follow up to create issues
    print("Creating issues for high-priority items...")
    print("-" * 40)

    meeting_tasks_agent.print_response(
        """Now create Linear issues for the top 3 highest priority action items
from the retrospective. Make sure to:
- Add appropriate labels (e.g., 'process', 'tech-debt', 'retro-action')
- Include context from the retrospective
- Set realistic priorities""",
        stream=True,
    )

    # Uncomment for interactive mode
    # meeting_tasks_agent.cli_app(stream=True)
