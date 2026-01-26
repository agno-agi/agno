"""Async example using Ollama with the OpenAI Responses API.

This demonstrates async usage with Ollama's Responses API endpoint.

Requirements:
- Ollama v0.13.3 or later running locally
- Run: ollama pull llama3.1:8b
"""

import asyncio

from agno.agent import Agent
from agno.models.ollama import OllamaResponses

agent = Agent(
    model=OllamaResponses(id="gpt-oss:20b"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
