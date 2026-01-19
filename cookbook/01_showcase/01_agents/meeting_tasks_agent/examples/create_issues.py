"""
Create Linear Issues from Meeting
=================================

Process meeting transcript and actually create Linear issues.
Demonstrates the full workflow from notes to tracked tasks.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/meeting_tasks_agent/examples/create_issues.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import MEETINGS_DIR, meeting_tasks_agent, process_meeting_file  # noqa: E402

# ============================================================================
# Create Issues Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Create Linear Issues from Meeting")
    print("=" * 60)
    print()
    print("This example will:")
    print("1. Read the sprint planning transcript")
    print("2. Extract action items")
    print("3. Get available Linear teams")
    print("4. Create issues in Linear (with your approval)")
    print()
    print("-" * 60)
    print()

    # First, check available teams
    print("Step 1: Getting available Linear teams...")
    print("-" * 40)
    meeting_tasks_agent.print_response(
        "What teams are available in Linear?",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Read the planning transcript
    transcript_file = MEETINGS_DIR / "planning_transcript.txt"
    meeting_content = process_meeting_file(str(transcript_file))

    print("Step 2: Processing meeting transcript...")
    print("-" * 40)

    meeting_tasks_agent.print_response(
        f"""Process this sprint planning meeting transcript.

1. First, extract all action items with owners and deadlines
2. Then, for EACH action item, create a Linear issue
   - Use clear, actionable titles
   - Include meeting context in the description
   - Set appropriate priority

Meeting Transcript:

{meeting_content}

Please proceed to create the issues in Linear.""",
        stream=True,
    )

    # Uncomment for interactive mode
    # meeting_tasks_agent.cli(stream=True)
