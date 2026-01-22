"""
Use Ollama with the Anthropic Messages API compatibility with tool use (requires Ollama v0.14.0+).

This allows you to use Ollama models with the Anthropic SDK, enabling compatibility
with tools and applications that expect the Anthropic API format.

Run `uv pip install ddgs` to install dependencies.
"""

from agno.agent import Agent
from agno.models.ollama import OllamaAnthropic
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=OllamaAnthropic(id="llama3.2:latest"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?")
