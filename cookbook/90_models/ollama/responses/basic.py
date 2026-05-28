"""Basic example using Ollama with the OpenAI Responses API.

This uses Ollama's OpenAI-compatible /v1/responses endpoint, which was added
in Ollama v0.13.3. It provides an alternative to the native Ollama API.

Requirements:
- Ollama v0.13.3 or later running locally
- Run: ollama pull llama3.1:8b
"""

import asyncio

from agno.agent import Agent
from agno.models.ollama import OllamaResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OllamaResponses(id="gpt-oss:20b"),
    markdown=True,
)

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Write a short poem about the moon", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
