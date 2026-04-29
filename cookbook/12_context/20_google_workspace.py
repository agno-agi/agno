"""
Google Workspace Multi-Provider
===============================

Combines GDrive, Gmail, and Calendar context providers into a single
agent. Each provider exposes its own query tool (query_gdrive, query_gmail,
query_calendar), allowing the agent to search across all three services.

This pattern demonstrates:
- Multiple context providers on one agent
- Shared authentication (all use the same SA or OAuth creds)
- Provider-specific sub-agents with specialized tools

Setup:
    Same as individual providers — OAuth or Service Account.
    For full workspace access, ensure all three APIs are enabled
    in your Google Cloud project.

Requires:
    OPENAI_API_KEY
    GOOGLE_SERVICE_ACCOUNT_FILE (with domain-wide delegation)
    GOOGLE_DELEGATED_USER
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.calendar import CalendarContextProvider
from agno.context.gdrive import GDriveContextProvider
from agno.context.gmail import GmailContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the providers
# ---------------------------------------------------------------------------
sub_model = OpenAIResponses(id="gpt-5.4-mini")

gdrive = GDriveContextProvider(model=sub_model)
gmail = GmailContextProvider(model=sub_model, read=True, write=False)
calendar = CalendarContextProvider(model=sub_model, read=True, write=False)

# ---------------------------------------------------------------------------
# Create the Agent with all providers
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
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Provider Status:")
    print(f"  gdrive:   {gdrive.status()}")
    print(f"  gmail:    {gmail.status()}")
    print(f"  calendar: {calendar.status()}")
    print()

    prompt = (
        "Find my most recent email from this week, check if it mentions a "
        "meeting, and if so, look up that meeting on my calendar. Also check "
        "if there are any related documents in Google Drive."
    )
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
