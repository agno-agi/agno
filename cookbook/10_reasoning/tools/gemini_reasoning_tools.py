"""
Gemini Reasoning Tools
======================

Demonstrates this reasoning cookbook example.
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    reasoning_agent = Agent(
        model=Gemini(id="gemini-2.5-pro"),
        tools=[
            ReasoningTools(
                enable_think=True,
                enable_analyze=True,
            ),
            YFinanceTools(),
        ],
        instructions="Use tables where possible",
        stream_events=True,
        markdown=True,
    )
    reasoning_agent.print_response(
        "Write a report comparing NVDA to TSLA.", show_full_reasoning=True
    )


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
