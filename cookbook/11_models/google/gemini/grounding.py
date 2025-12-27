"""Grounding with Gemini.

Grounding enables Gemini to search the web and provide responses backed by
real-time information with citations. This is a legacy tool - for Gemini 2.0+
models, consider using the 'search' parameter instead.

Run `pip install google-generativeai` to install dependencies.
"""

from agno.agent import Agent
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash",
        grounding=True,
        grounding_dynamic_threshold=0.7,  # Optional: set threshold for grounding
    ),
    add_datetime_to_context=True,
)

# Ask questions that benefit from real-time information
agent.print_response(
    "What are the current market trends in renewable energy?",
    stream=True,
    markdown=True,
)
