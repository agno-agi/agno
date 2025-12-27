"""
This example shows how to add observability to your agno agent with Atla.

1. Install dependencies: pip install "atla-insights"
2. Sign up for an account at https://app.atla-ai.com
3. Set your Atla Insights API key as an environment variable:
  - export ATLA_API_KEY=<your-key>
"""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from atla_insights import configure, instrument_agno

configure(token=getenv("ATLA_API_KEY"))

agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
    debug_mode=True,
)

# Instrument and run
with instrument_agno("openai"):
    agent.print_response("What are the latest news about the stock market?")
