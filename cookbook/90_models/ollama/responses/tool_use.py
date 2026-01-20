"""Tool use example using Ollama with the OpenAI Responses API.

This demonstrates using tools with Ollama's Responses API endpoint.

Requirements:
- Ollama v0.13.3 or later running locally
- Run: ollama pull llama3.1:8b
"""

from agno.agent import Agent
from agno.models.ollama import OllamaResponses
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OllamaResponses(id="llama3.1:8b", host="http://localhost:11434"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("What is the latest news about AI?", stream=True)
