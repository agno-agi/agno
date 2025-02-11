"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.google import GeminiOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=GeminiOpenAI(id="gemini-2.0-flash-exp"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Whats happening in France?")
