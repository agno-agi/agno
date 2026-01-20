"""
Use Ollama with the Anthropic Messages API compatibility (requires Ollama v0.14.0+).

This allows you to use Ollama models with the Anthropic SDK, enabling compatibility
with tools and applications that expect the Anthropic API format.

By default, connects to http://localhost:11434. Set OLLAMA_HOST env var to override.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.ollama import OllamaAnthropic

agent = Agent(
    model=OllamaAnthropic(id="llama3.1:8b"),
    markdown=True,
)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")
