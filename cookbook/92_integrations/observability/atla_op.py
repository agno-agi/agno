"""
Atla Observability Integration
==============================

Demonstrates adding Atla observability to an Agno agent.
"""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from atla_insights import configure, instrument_agno

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
configure(token=getenv("ATLA_API_KEY"))


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
    debug_mode=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Instrument and run
    with instrument_agno("openai"):
        agent.print_response("What are the latest news about the stock market?")
