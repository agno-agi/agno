"""
Process Meeting Notes
=====================

Extract action items from meeting notes and create Linear issues.
Demonstrates action item extraction from a single meeting.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/meeting_tasks_agent/examples/01_process_notes.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import MEETINGS_DIR, meeting_tasks_agent, process_meeting_file  # noqa: E402

# ============================================================================
# Process Meeting Notes Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Process Meeting Notes")
    print("=" * 60)
    print()
    print("This example will:")
    print("1. Read the standup meeting notes")
    print("2. Extract action items")
    print("3. Identify owners and deadlines")
    print("4. Show what Linear issues would be created")
    print()
    print("-" * 60)
    print()

    # Read the standup notes
    notes_file = MEETINGS_DIR / "standup_notes.md"
    meeting_content = process_meeting_file(str(notes_file))

    print("Meeting Content:")
    print("-" * 40)
    print(meeting_content[:500] + "...")
    print()
    print("-" * 60)
    print()

    # Process with the agent
    meeting_tasks_agent.print_response(
        f"""Process these meeting notes and extract all action items.

For each action item:
1. Identify the task description
2. Determine the owner (who should do it)
3. Extract any deadline
4. Assign priority based on context

After extraction, show me:
- Summary of the meeting
- List of all action items with owners and deadlines
- Which items should become Linear issues

Here are the meeting notes:

{meeting_content}""",
        stream=True,
    )

    # Uncomment for interactive mode
    # meeting_tasks_agent.cli(stream=True)
