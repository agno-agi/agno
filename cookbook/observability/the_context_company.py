"""
The Context Company
===================

Demonstrates instrumenting an Agno agent with The Context Company.

Setup:
    pip install "contextcompany[agno]>=1.9.1" agno openai yfinance

Set TCC_API_KEY and OPENAI_API_KEY before running this example.
See https://docs.thecontextcompany.com/frameworks/agno for the complete setup guide.
"""

import asyncio

from contextcompany.agno import instrument_agno

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Initialize instrumentation before importing Agno.
instrument_agno()

from agno.agent import Agent  # noqa: E402
from agno.models.openai import OpenAIChat  # noqa: E402
from agno.tools.yfinance import YFinanceTools  # noqa: E402

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-5.2"),
    tools=[YFinanceTools()],
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
async def main() -> None:
    await agent.aprint_response(
        "What is the current price of Tesla? Then find the current price of NVIDIA.",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
