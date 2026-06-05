"""
Full Workspace Agent
====================

All Google Workspace tools in one agent. Maximum capability.

Includes: Gmail, Calendar, Drive, Sheets, Slides, Meet, Tasks

Use cases:
- Complex multi-step workflows
- Research across documents and emails
- Meeting prep with related docs
- Full daily workflow automation

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/full_workspace_agent.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.meet import GoogleMeetTools
from agno.tools.google.sheets import GoogleSheetsTools
from agno.tools.google.slides import GoogleSlidesTools
from agno.tools.google.tasks import GoogleTasksTools

auth = GoogleAuth()

agent = Agent(
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(auth=auth),
        GoogleCalendarTools(auth=auth),
        GoogleDriveTools(auth=auth),
        GoogleSheetsTools(auth=auth),
        GoogleSlidesTools(auth=auth),
        GoogleMeetTools(),
        GoogleTasksTools(),
    ],
    instructions=[
        "You have full access to Google Workspace.",
        "Plan multi-step tasks carefully before executing.",
        "When working across services, gather context first.",
        "Summarize results clearly at the end of complex operations.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "What's my schedule for today? Check if any meetings have related documents in Drive.",
        stream=True,
    )
