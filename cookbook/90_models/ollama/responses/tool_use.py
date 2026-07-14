"""Tool use example using Ollama with the OpenAI Responses API.

This demonstrates using tools with Ollama's Responses API endpoint.

Requirements:
- Ollama v0.13.3 or later running locally
- Run: ollama pull llama3.1:8b
"""

from agno.agent import Agent
from agno.models.ollama import OllamaResponses
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OllamaResponses(id="gpt-oss:20b"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What is the latest news about AI?")

    # --- Sync + Streaming ---
    agent.print_response("What is the latest news about AI?", stream=True)
