"""
Multiple Calendars — Tools Mode
===============================

Two Google Calendar providers with mode=ContextMode.tools: one for work,
one for personal. Each provider prefixes its tools with its id:

- ``work_get_events``, ``work_search_events``, ``work_list_calendars``
- ``personal_get_events``, ``personal_search_events``, ``personal_list_calendars``

The agent can query both calendars simultaneously without tool name collisions.
Use case: "Am I free Thursday?" checks both work and personal calendars.

Setup:
    Work calendar (service account)::
        export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/work-sa.json

    Personal calendar (OAuth)::
        export GOOGLE_CLIENT_ID=...
        export GOOGLE_CLIENT_SECRET=...
        export GOOGLE_PROJECT_ID=...

    Or use two service accounts with different paths.

Requires: OPENAI_API_KEY + calendar credentials
"""

try:
    from agno.context.calendar import GoogleCalendarContextProvider
except ImportError:
    print("Google client libraries not found. Install with:")
    print("  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
    raise SystemExit(1)

from agno.agent import Agent
from agno.context.mode import ContextMode
from agno.models.openai import OpenAIResponses

# Work calendar — service account (or first OAuth token)
work = GoogleCalendarContextProvider(
    id="work",
    name="Work Calendar",
    mode=ContextMode.tools,
    # Uses GOOGLE_SERVICE_ACCOUNT_FILE by default
)

# Personal calendar — different credentials
# In practice, use a different token_path or service account
personal = GoogleCalendarContextProvider(
    id="personal",
    name="Personal Calendar",
    mode=ContextMode.tools,
    token_path="personal_calendar_token.json",  # Separate OAuth token
)

# Combine tools — no collision because of prefixing
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[*work.get_tools(), *personal.get_tools()],
    instructions=(
        "You have access to two calendars:\n\n"
        f"{work.instructions()}\n\n"
        f"{personal.instructions()}\n\n"
        "When checking availability, query BOTH calendars. "
        "Use work_* tools for work calendar, personal_* tools for personal."
    ),
    markdown=True,
)


if __name__ == "__main__":
    # Show prefixed tool names
    print("Work calendar tools:")
    for toolkit in work.get_tools():
        for name in toolkit.functions:
            print(f"  - {name}")

    print("\nPersonal calendar tools:")
    for toolkit in personal.get_tools():
        for name in toolkit.functions:
            print(f"  - {name}")

    print("\nNote: This example requires Google Calendar credentials.")
    print("Set up service account or OAuth credentials, then run:")
    print("  agent.print_response('Am I free Thursday afternoon?')")
