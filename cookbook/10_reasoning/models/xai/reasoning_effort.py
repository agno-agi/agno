"""
Reasoning Effort
================

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.xai import xAI
from agno.tools.yfinance import YFinanceTools


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    agent = Agent(
        model=xAI(id="grok-3-mini-fast", reasoning_effort="high"),
        tools=[YFinanceTools()],
        instructions="Use tables to display data.",
        markdown=True,
    )
    agent.print_response("Write a report comparing NVDA to TSLA", stream=True)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
