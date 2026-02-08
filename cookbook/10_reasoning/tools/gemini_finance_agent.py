"""
Gemini Finance Agent
====================

Demonstrates this reasoning cookbook example.
"""
# ! pip install -U agno

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    thinking_agent = Agent(
        model=Gemini(id="gemini-3-flash-preview"),
        tools=[
            ReasoningTools(add_instructions=True),
            YFinanceTools(),
        ],
        instructions="Use tables where possible",
        markdown=True,
        stream_events=True,
    )
    thinking_agent.print_response(
        "Write a report comparing NVDA to TSLA in detail",
        stream=True,
        show_reasoning=True,
    )


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
