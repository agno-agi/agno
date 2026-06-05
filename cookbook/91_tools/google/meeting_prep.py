"""
Meeting Prep Agent
==================

Prepare for meetings by gathering context from email threads,
related documents, and previous meeting notes.

Use cases:
- Pull together context before a meeting
- Find related email threads with attendees
- Locate relevant documents in Drive
- Summarize past discussions

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/meeting_prep.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.meet import GoogleMeetTools

auth = GoogleAuth()

agent = Agent(
    name="Meeting Prep",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GoogleCalendarTools(auth=auth, include_tools=["list_events", "get_event"]),
        GmailTools(auth=auth, include_tools=["search_emails", "get_emails_by_thread"]),
        GoogleDriveTools(auth=auth),
        GoogleMeetTools(auth=auth),
    ],
    instructions=[
        "You help prepare for meetings by gathering context.",
        "For each meeting, identify: attendees, topic, related emails, relevant docs.",
        "Search email for recent threads with meeting attendees.",
        "Search Drive for documents related to the meeting topic.",
        "Provide a concise briefing with key points to discuss.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "I have meetings today. Help me prepare by finding related emails and documents for each.",
        stream=True,
    )
