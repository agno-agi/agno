"""
AWS Bedrock Tool Use
====================

Basic example of using tools with AWS Bedrock models.
For advanced tool_choice options, see tool_choice.py.

Run `uv pip install ddgs` to install web search dependencies.
"""

import asyncio

from agno.agent import Agent
from agno.models.aws import AwsBedrock
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent with Tools
# ---------------------------------------------------------------------------

agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[WebSearchTools()],
    instructions="You are a helpful assistant that can search the web.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Sync
    agent.print_response("What's happening in France?")

    # Sync + Streaming
    agent.print_response("What's the latest news about AI?", stream=True)

    # Async + Streaming
    asyncio.run(agent.aprint_response("Who won the last World Cup?", stream=True))
