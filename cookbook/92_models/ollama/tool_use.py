"""Run `uv pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.ollama import Ollama
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Ollama(id="llama3.2:latest"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?")
