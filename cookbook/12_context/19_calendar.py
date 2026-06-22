"""
Google Calendar Context Provider
================================

GoogleCalendarContextProvider gives agents read/write access to Google Calendar
through specialized sub-agents. The calling agent receives:

- ``query_calendar`` — list events, check availability, find free slots
- ``update_calendar`` — create, update, delete events (when write=True)

This example demonstrates:
1. Read-only mode: checking schedule and availability
2. Read-write mode: scheduling a new meeting

Compare with: 18_gmail.py for email operations
See also: 20_google_workspace.py for multi-provider workflows

Setup (OAuth - recommended for personal calendar):
    1. Create OAuth credentials in Google Cloud Console
       - APIs & Services > Credentials > Create OAuth Client ID
       - Application type: Desktop app
    2. Enable the Google Calendar API in your project
    3. Set environment variables::

           export GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
           export GOOGLE_CLIENT_SECRET=GOCSPX-...
           export GOOGLE_PROJECT_ID=your-project-id

    4. First run opens browser for consent, token cached to calendar_token.json

Setup (Service Account - for Google Workspace):
    1. Create service account (domain-wide delegation optional)
    2. Without delegation: operates on the service account's own calendar
    3. With delegation: can access user calendars
    4. Set environment variables::

           export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account.json
           export GOOGLE_DELEGATED_USER=user@yourdomain.com  # optional

Requires: OPENAI_API_KEY + one of the auth methods above
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.calendar import GoogleCalendarContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Example 1: Read-Only Calendar Access
# ---------------------------------------------------------------------------
# Use read=True, write=False when you only need to check schedules.
# The agent gets query_calendar but NOT update_calendar.


async def demo_read_only():
    print("\n" + "=" * 60)
    print("DEMO 1: Read-Only Calendar Access")
    print("=" * 60)

    calendar = GoogleCalendarContextProvider(
        model=OpenAIResponses(id="gpt-5.4-mini"),
        read=True,
        write=False,
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=calendar.get_tools(),
        instructions=calendar.instructions(),
        markdown=True,
    )

    print(f"\nProvider status: {calendar.status()}")
    print("\n--- Query: What's on my calendar this week? ---\n")

    await agent.aprint_response(
        "What meetings do I have this week? "
        "For each meeting, tell me the day, time, title, and who's attending. "
        "Highlight any conflicts or back-to-back meetings.",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Example 2: Read-Write Calendar Access
# ---------------------------------------------------------------------------
# Use write=True when the agent needs to create or modify events.
# The agent gets both query_calendar and update_calendar tools.


async def demo_read_write():
    print("\n" + "=" * 60)
    print("DEMO 2: Read-Write Calendar Access")
    print("=" * 60)

    calendar = GoogleCalendarContextProvider(
        model=OpenAIResponses(id="gpt-5.4-mini"),
        read=True,
        write=True,
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=calendar.get_tools(),
        instructions=calendar.instructions(),
        markdown=True,
    )

    print(f"\nProvider status: {calendar.status()}")
    print("\n--- Query: Find a slot and schedule a meeting ---\n")

    await agent.aprint_response(
        "Find a 30-minute slot tomorrow afternoon when I'm free, "
        "and create a meeting called 'Weekly Planning' at that time.",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Run Demos
# ---------------------------------------------------------------------------


async def main():
    await demo_read_only()
    await demo_read_write()


if __name__ == "__main__":
    asyncio.run(main())
