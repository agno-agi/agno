"""
Tool Confirmation — Dojo Demo
=============================

Frontend-provided tools: send_email, delete_files (via useHumanInTheLoop)

The frontend defines these tools as requiring confirmation before execution.
When the agent calls them, the frontend renders a confirmation card.
User can approve or reject the action.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

tool_confirmation_agent = Agent(
    name="tool_confirmation",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/agui_tool_confirmation.db"),
    instructions="""You are an assistant that can send emails and delete files.
Both actions require user confirmation before execution.

When asked to send an email:
- Call the send_email tool with: to, subject, body
- Wait for user confirmation

When asked to delete files:
- Call the delete_files tool with: action, description, details
- Wait for user confirmation

Example email tool call:
{
  "to": "alice@example.com",
  "subject": "Hello!",
  "body": "Just wanted to say hi."
}

Example delete tool call:
{
  "action": "Delete temporary files",
  "description": "Remove all .tmp files from the project",
  "details": {"count": "15 files", "size": "2.3 MB"}
}

After user confirms or rejects:
- Acknowledge the decision
- If confirmed, confirm the action was taken
- If rejected, acknowledge and ask if there's anything else""",
    markdown=True,
)
