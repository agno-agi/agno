"""
Use Ollama with the Anthropic Messages API compatibility with streaming (requires Ollama v0.14.0+).

This allows you to use Ollama models with the Anthropic SDK, enabling compatibility
with tools and applications that expect the Anthropic API format.

By default, connects to http://localhost:11434. Set OLLAMA_HOST env var to override.
"""

from agno.agent import Agent
from agno.models.ollama import OllamaAnthropic

agent = Agent(
    model=OllamaAnthropic(id="llama3.1:8b"),
    markdown=True,
)

# Stream the response
agent.print_response("Share a 2 sentence horror story", stream=True)
