"""
Adanos Market Sentiment Tools
=============================

Demonstrates cross-platform stock and crypto sentiment research with Adanos.

Requirements:
- An Adanos API key from https://adanos.org/register

Set the following environment variable (or pass the key to AdanosTools):

    export ADANOS_API_KEY="your_api_key"
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.adanos import AdanosTools

agent = Agent(
    name="Market Sentiment Research Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[AdanosTools()],
    instructions=[
        "Compare sentiment across available sources before drawing conclusions.",
        "Treat sentiment as research context, not as trading advice.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Compare AAPL sentiment on Reddit, X, financial news, and Polymarket over the last seven UTC days."
    )
