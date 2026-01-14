"""Combine URL context with Google Search for comprehensive web analysis.

Run `pip install google-generativeai` to install dependencies.
"""

from agno.agent import Agent
from agno.models.google import Gemini

# Create agent with both Google Search and URL context enabled
agent = Agent(
    model=Gemini(id="gemini-2.5-flash", search=True, url_context=True),
    markdown=True,
)

# The agent will first search for relevant URLs, then analyze their content in detail
agent.print_response(
    "Analyze the content of the following URL: https://docs.agno.com/introduction and also give me latest updates on AI agents"
)
