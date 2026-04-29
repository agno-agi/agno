"""
Google Calendar Context Provider
================================

CalendarContextProvider wraps GoogleCalendarTools for read/write
calendar access. The calling agent gets `query_<id>` and optionally
`update_<id>` tools that route through sub-agents specialized for
searching/reading vs creating/updating events.

Setup (OAuth - recommended for personal calendar):
    1. Create OAuth credentials in Google Cloud Console
    2. Set env vars:
           export GOOGLE_CLIENT_ID=...
           export GOOGLE_CLIENT_SECRET=...
           export GOOGLE_PROJECT_ID=...
    3. On first run, a browser opens for consent. Token cached to calendar_token.json

Setup (Service Account - for workspace bots):
    1. Create service account (domain-wide delegation optional)
    2. Without delegation: operates on the SA's own calendar
    3. With delegation: impersonates a user's calendar
    4. Set env vars:
           export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/sa.json
           export GOOGLE_DELEGATED_USER=user@domain.com  # optional

Requires:
    OPENAI_API_KEY
    + one of the auth methods above
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.calendar import CalendarContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider (auth method resolved from env)
# ---------------------------------------------------------------------------
calendar = CalendarContextProvider(
    model=OpenAIResponses(id="gpt-5.4-mini"),
    read=True,
    write=False,
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=calendar.get_tools(),
    instructions=calendar.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\ncalendar.status() = {calendar.status()}\n")
    prompt = (
        "What meetings do I have in the next 7 days? List each with date, "
        "time, title, and attendees."
    )
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
