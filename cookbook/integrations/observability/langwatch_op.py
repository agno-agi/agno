"""
This example shows how to instrument your agno agent and send traces to LangWatch.

1. Install dependencies: pip install openai langwatch openinference-instrumentation-agno
2. Sign up for an account at https://app.langwatch.ai/
3. Set your LangWatch API key as an environment variables:
  - export LANGWATCH_API_KEY=<your-key>
"""

import langwatch
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from openinference.instrumentation.agno import AgnoInstrumentor

# Initialize LangWatch and instrument Agno
langwatch.setup(instrumentors=[AgnoInstrumentor()])

# Create and configure your Agno agent
agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YFinanceTools()],
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
    debug_mode=True,
)

agent.print_response("What is the current price of Tesla?")
