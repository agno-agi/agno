"""
Email to Tasks Sync Agent
=========================

Extract action items from emails and create tasks automatically.
Combines Gmail + Tasks for inbox processing.

Use cases:
- Scan unread emails for action items
- Create tasks from email requests
- Track follow-ups needed
- Daily inbox cleanup

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/email_task_sync.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.gmail import GmailTools
from agno.tools.google.tasks import GoogleTasksTools

auth = GoogleAuth()

agent = Agent(
    name="Email Task Sync",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(
            auth=auth,
            include_tools=["search_emails", "get_emails_by_thread", "mark_email_as_read"],
        ),
        GoogleTasksTools(),
    ],
    instructions=[
        "You process emails and extract action items into tasks.",
        "Look for requests, deadlines, and follow-up needs in emails.",
        "Create tasks with clear titles that reference the email sender.",
        "Set due dates based on urgency mentioned in emails.",
        "Mark processed emails as read after creating tasks.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Check my unread emails from today and create tasks for any action items you find",
        stream=True,
    )
