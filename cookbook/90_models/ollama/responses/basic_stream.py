"""Streaming example using Ollama with the OpenAI Responses API.

This uses Ollama's OpenAI-compatible /v1/responses endpoint with streaming.

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

# Stream the response
agent.print_response("Write a short poem about the moon", stream=True)
