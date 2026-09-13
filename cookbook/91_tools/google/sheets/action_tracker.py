"""
Action Item Tracker
===================

Read meeting notes from a sheet, extract action items with owners and due dates,
and write them to a tracking sheet.

Setup:
  1. Create a Google Sheet with meeting notes (free-form text in a column)
  2. Set MEETING_NOTES_SHEET_ID env var
  3. Set Google OAuth credentials (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)

Example Input Sheet (Meeting Notes):
  | Date       | Meeting         | Notes                                                    |
  |------------|-----------------|----------------------------------------------------------|
  | 2026-06-15 | Product Sync    | @alice to finalize specs by Friday. @bob to review PRD. |
  | 2026-06-14 | Sprint Planning | @carol owns the auth refactor. Due next Tuesday.        |

Output (Action Items):
  | Action Item           | Owner | Due Date   | Source Meeting  | Status  |
  |-----------------------|-------|------------|-----------------|---------|
  | Finalize specs        | alice | 2026-06-20 | Product Sync    | Pending |
  | Review PRD            | bob   |            | Product Sync    | Pending |
  | Auth refactor         | carol | 2026-06-24 | Sprint Planning | Pending |

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/sheets/action_tracker.py
"""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.sheets import GoogleSheetsTools

agent = Agent(
    name="Action Tracker",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        GoogleSheetsTools(
            read_sheet=True,
            update_sheet=True,
        )
    ],
    instructions=[
        "You extract action items from meeting notes and track them.",
        "Look for patterns like '@name to do X' or 'X owns Y' or 'due by Z'.",
        "Extract: the action item, owner (person responsible), and due date if mentioned.",
        "Write extracted items to the specified output sheet.",
        "Set status to 'Pending' for new items.",
        "Be thorough - capture all commitments, not just explicit action items.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    notes_sheet = getenv("MEETING_NOTES_SHEET_ID")
    output_sheet = getenv("ACTION_ITEMS_SHEET_ID", notes_sheet)

    if not notes_sheet:
        print("Set MEETING_NOTES_SHEET_ID to your meeting notes spreadsheet ID")
        print(
            "Optionally set ACTION_ITEMS_SHEET_ID for output (defaults to same sheet)"
        )
        exit(1)

    agent.print_response(
        f"Read the meeting notes from spreadsheet {notes_sheet}, extract all action items "
        f"with owners and due dates, then write them to the 'Action Items' tab in {output_sheet}. "
        "Create the tab if it doesn't exist.",
        stream=True,
    )
