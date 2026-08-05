"""
Google Workspace Multi-Provider
===============================

Combines GDrive, Gmail, and Calendar context providers into a single
agent for cross-service workflows. Each provider exposes its own tools:

- ``query_gdrive`` — search and read Google Drive files
- ``query_gmail`` / ``update_gmail`` — email operations
- ``query_calendar`` / ``update_calendar`` — calendar operations

This pattern demonstrates real-world workflows that span multiple services:
1. Meeting prep: calendar + email + drive
2. Follow-up workflow: email + calendar + draft

Compare with: 18_gmail.py, 19_calendar.py for single-provider examples
See also: GoogleDriveContextProvider in context/gdrive/ for Drive-only access

Setup:
    All providers share the same OAuth or service account credentials.
    Ensure Gmail, Calendar, and Drive APIs are all enabled in your
    Google Cloud project.

    OAuth (personal workspace)::

        export GOOGLE_CLIENT_ID=...
        export GOOGLE_CLIENT_SECRET=...
        export GOOGLE_PROJECT_ID=...

    Service Account (Google Workspace)::

        export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/sa.json
        export GOOGLE_DELEGATED_USER=user@domain.com

Requires: OPENAI_API_KEY + auth credentials above
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.calendar import GoogleCalendarContextProvider
from agno.context.gdrive import GoogleDriveContextProvider
from agno.context.gmail import GmailContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Providers
# ---------------------------------------------------------------------------
# All providers share the same auth (resolved from env vars).
# Using gpt-5.4-mini for sub-agents keeps costs low while the main
# agent uses gpt-5.4 for better reasoning across multiple tools.

sub_model = OpenAIResponses(id="gpt-5.4-mini")

gdrive = GoogleDriveContextProvider(model=sub_model)
gmail = GmailContextProvider(model=sub_model, read=True, write=True)
calendar = GoogleCalendarContextProvider(model=sub_model, read=True, write=True)

# ---------------------------------------------------------------------------
# Create Multi-Provider Agent
# ---------------------------------------------------------------------------

all_tools = gdrive.get_tools() + gmail.get_tools() + calendar.get_tools()
combined_instructions = "\n\n".join(
    [
        gdrive.instructions(),
        gmail.instructions(),
        calendar.instructions(),
    ]
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=all_tools,
    instructions=combined_instructions,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Demo 1: Meeting Preparation Workflow
# ---------------------------------------------------------------------------
# A realistic Scout use case: preparing for an upcoming meeting by
# gathering context from calendar, email, and shared documents.


async def demo_meeting_prep():
    print("\n" + "=" * 60)
    print("DEMO 1: Meeting Preparation Workflow")
    print("=" * 60)

    print("\nProvider Status:")
    print(f"  gdrive:   {gdrive.status()}")
    print(f"  gmail:    {gmail.status()}")
    print(f"  calendar: {calendar.status()}")

    print("\n--- Query: Prepare for my next meeting ---\n")

    await agent.aprint_response(
        "Help me prepare for my next meeting. "
        "Find the meeting on my calendar, then search for any recent emails "
        "from the attendees, and look for related documents in Google Drive. "
        "Give me a briefing with the key context I need.",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Demo 2: Follow-Up Workflow
# ---------------------------------------------------------------------------
# Another Scout use case: finding items that need follow-up across
# email and calendar, then taking action.


async def demo_follow_up():
    print("\n" + "=" * 60)
    print("DEMO 2: Follow-Up Workflow")
    print("=" * 60)

    print("\n--- Query: What needs my attention? ---\n")

    await agent.aprint_response(
        "What needs my attention today? "
        "Check my unread emails and today's calendar. "
        "For any meeting that just happened, draft a follow-up email "
        "summarizing action items if the email thread suggests there were any.",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Demo 3: Quick Status Check
# ---------------------------------------------------------------------------
# Fast parallel query to all providers for a morning briefing.


async def demo_morning_briefing():
    print("\n" + "=" * 60)
    print("DEMO 3: Morning Briefing")
    print("=" * 60)

    print("\n--- Query: Quick morning status ---\n")

    await agent.aprint_response(
        "Give me a quick morning briefing: "
        "What meetings do I have today? "
        "Any urgent unread emails? "
        "Any recently shared documents I should review?",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Run Demos
# ---------------------------------------------------------------------------


async def main():
    await demo_meeting_prep()
    await demo_follow_up()
    await demo_morning_briefing()


if __name__ == "__main__":
    asyncio.run(main())
