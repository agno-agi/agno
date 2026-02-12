"""
Output Schema
=============================

This example shows how to use the output_model parameter to specify the model that will be used to generate the final response.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    output_model=OpenAIChat(id="o3-mini"),
    tools=[WebSearchTools()],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Latest news from France?", stream=True)
