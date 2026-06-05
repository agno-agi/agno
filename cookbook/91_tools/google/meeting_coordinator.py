"""
Meeting Coordinator Agent
=========================

Schedule meetings with Google Meet links and send invites via Gmail.
Combines Calendar + Meet + Gmail in one workflow.

Use cases:
- Schedule a meeting and create a Meet link
- Send meeting invites with agenda
- Find available time slots
- Reschedule with notifications

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/meeting_coordinator.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.meet import GoogleMeetTools

auth = GoogleAuth()

agent = Agent(
    name="Meeting Coordinator",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GoogleCalendarTools(
            auth=auth,
            include_tools=["list_events", "create_event", "get_event", "update_event"],
        ),
        GoogleMeetTools(auth=auth),
        GmailTools(auth=auth, include_tools=["create_draft", "send_email"]),
    ],
    instructions=[
        "You coordinate meetings and handle scheduling.",
        "When creating a meeting, always create a Google Meet link.",
        "Include the Meet link in any email invites.",
        "Check for calendar conflicts before scheduling.",
        "Suggest alternative times if there are conflicts.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Schedule a 30-minute team sync for tomorrow afternoon and draft an invite email with the Meet link",
        stream=True,
    )
