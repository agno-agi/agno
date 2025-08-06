"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.ollama import Ollama

agent = Agent(
    model=Ollama(id="gpt-oss:20b"),
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Whats happening in France?")
