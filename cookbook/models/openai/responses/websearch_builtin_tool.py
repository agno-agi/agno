"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-4o", web_search=True),
    markdown=True,
)
agent.print_response("Whats happening in France?")
