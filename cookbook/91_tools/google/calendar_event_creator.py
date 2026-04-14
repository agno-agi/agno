"""
Calendar Event Creator
======================
Creates detailed calendar events from natural language descriptions.

The agent parses complex event requests and uses create_event with all available
parameters: title, description, location, attendees, timezone, and Google Meet links.

Key concepts:
- create_event: full event creation with attendees and conferencing
- update_event: modify existing events after creation
- add_datetime_to_context: agent knows "now" for relative date references

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Calendar API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.calendar import GoogleCalendarTools

agent = Agent(
    name="Event Creator",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleCalendarTools()],
    instructions=[
        "When creating events, always include a clear title and appropriate timezone.",
        "For meetings with others, add attendees and a Google Meet link.",
        "Use the description field for agenda items or context.",
        "After creating an event, confirm the details back to the user.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

# Save OAuth token to DB instead of token.json
# from agno.db.sqlite.sqlite import SqliteDb
# from agno.models.openai import OpenAIResponses
# db_agent = Agent(
#     name="Calendar Agent (DB)",
#     model=OpenAIResponses(id="gpt-5.4"),
#     tools=[GoogleCalendarTools(store_token_in_db=True)],
#     db=SqliteDb(db_file="tmp/calendar.db"),
#     add_datetime_to_context=True,
#     markdown=True,
# )


if __name__ == "__main__":
    agent.print_response(
        "Create a 1-hour product review meeting next Tuesday at 2pm EST "
        "in Conference Room B with alice@company.com and bob@company.com. "
        "Add a Google Meet link. In the description, note that we'll be "
        "reviewing the Q1 roadmap and discussing launch timelines.",
        stream=True,
    )
