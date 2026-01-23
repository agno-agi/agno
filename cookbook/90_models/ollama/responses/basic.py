"""Basic example using Ollama with the OpenAI Responses API.

This uses Ollama's OpenAI-compatible /v1/responses endpoint, which was added
in Ollama v0.13.3. It provides an alternative to the native Ollama API.

Requirements:
- Ollama v0.13.3 or later running locally
- Run: ollama pull llama3.1:8b
"""

from agno.agent import Agent
from agno.models.ollama import OllamaResponses

agent = Agent(
    model=OllamaResponses(id="gpt-oss:20b"),
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")
