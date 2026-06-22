"""
LangWatch Integration
=====================

Demonstrates instrumenting an Agno agent and sending traces to LangWatch.
"""

import langwatch
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from openinference.instrumentation.agno import AgnoInstrumentor

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Initialize LangWatch and instrument Agno
langwatch.setup(instrumentors=[AgnoInstrumentor()])


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
