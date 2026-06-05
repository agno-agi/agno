"""
Executive Assistant Agent
=========================

Daily briefing agent combining Gmail, Calendar, and Tasks.
Shared auth means ONE OAuth consent for all three services.

Use cases:
- Morning briefing: emails, meetings, pending tasks
- Schedule management: find free slots, reschedule conflicts
- Task prioritization: what needs attention today

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/executive_assistant.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.tasks import GoogleTasksTools

auth = GoogleAuth()

agent = Agent(
    name="Executive Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(auth=auth, include_tools=["search_emails", "get_emails_by_thread"]),
        GoogleCalendarTools(auth=auth, include_tools=["list_events", "get_event"]),
        GoogleTasksTools(),
    ],
    instructions=[
        "You are an executive assistant helping manage the day.",
        "When giving a briefing, organize by priority: urgent emails first, then meetings, then tasks.",
        "For calendar conflicts, suggest resolution options.",
        "Be concise but thorough.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Give me my morning briefing: important emails from today, meetings scheduled, and pending tasks",
        stream=True,
    )
