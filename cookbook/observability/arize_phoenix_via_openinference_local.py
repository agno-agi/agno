"""
Arize Phoenix Local Via OpenInference
=====================================

Demonstrates instrumenting an Agno agent and sending traces to a local Phoenix instance.
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from phoenix.otel import register

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = "http://localhost:6006"

# Configure the Phoenix tracer
tracer_provider = register(
    project_name="agno-stock-price-agent",  # Default is 'default'
    auto_instrument=True,  # Automatically use the installed OpenInference instrumentation
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-5.2"),
    tools=[YFinanceTools()],
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
    debug_mode=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the current price of Tesla?")
