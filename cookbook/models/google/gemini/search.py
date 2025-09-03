"""Google Search with Gemini.

The search tool enables Gemini to access current information from Google Search.
This is useful for getting up-to-date facts, news, and web content.

Run `pip install google-generativeai` to install dependencies.
"""

from agno.agent import Agent
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp", search=True),
    show_tool_calls=True,
    markdown=True,
)

# Ask questions that require current information
agent.print_response("What are the latest developments in AI technology this week?")
