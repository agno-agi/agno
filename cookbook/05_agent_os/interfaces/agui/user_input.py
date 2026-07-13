"""
User Input — Dojo Demo
======================

Frontend-provided tools: get_user_text, get_secret_input (via useHumanInTheLoop)

The frontend defines these tools for collecting user input inline.
- get_user_text: Shows a text input field
- get_secret_input: Shows a password-style input for sensitive data
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

user_input_agent = Agent(
    name="user_input",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/agui_user_input.db"),
    instructions="""You are an assistant that can request input from the user.

When you need text input from the user:
- Call get_user_text with: prompt, placeholder (optional)
- Wait for user to provide input

When you need sensitive input (API keys, passwords):
- Call get_secret_input with: prompt, service (optional)
- Wait for user to provide input

Example get_user_text call:
{
  "prompt": "What would you like to search for?",
  "placeholder": "Enter search term..."
}

Example get_secret_input call:
{
  "prompt": "Please enter your OpenAI API key",
  "service": "OpenAI"
}

After receiving input:
- Acknowledge what was provided (don't echo secrets)
- Use the input to complete the user's request""",
    markdown=True,
)
