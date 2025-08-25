"""
This example shows how to instrument your agno agent with Langtrace.

1. Install dependencies: pip install langtrace-python-sdk
2. Sign up for an account at https://app.langtrace.ai/
3. Set your Langtrace API key as an environment variables:
  - export LANGTRACE_API_KEY=<your-key>
"""

# Must precede other imports
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from langtrace_python_sdk import langtrace  # type: ignore

langtrace.init()

agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YFinanceTools()],
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
    debug_mode=True,
)

agent.print_response("What is the current price of Tesla?")
