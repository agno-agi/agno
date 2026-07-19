"""
Backend Feedback — Dojo Demo
============================

Frontend-provided tool: get_user_choice (via useHumanInTheLoop)

The frontend defines this tool for presenting multiple choices to the user.
When called, it renders a card with radio buttons for selection.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

backend_feedback_agent = Agent(
    name="backend_feedback",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/agui_backend_feedback.db"),
    instructions="""You are an assistant that helps users make decisions.

When you need the user to choose from options:
- Call get_user_choice with: question, options (array of strings)
- Wait for user to select an option

Example get_user_choice call:
{
  "question": "What type of cuisine would you prefer for dinner?",
  "options": ["Italian", "Japanese", "Mexican", "Indian", "Thai"]
}

After receiving the selection:
- Acknowledge their choice
- Provide relevant recommendations or next steps based on their selection
- Ask follow-up questions if needed using get_user_choice again""",
    markdown=True,
)
