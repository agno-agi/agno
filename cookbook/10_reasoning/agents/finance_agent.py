"""
Reasoning Finance Agent
=======================

Demonstrates DeepSeek-backed reasoning with tools for financial reporting.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6"),
    tools=[YFinanceTools()],
    instructions=["Use tables where possible"],
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Write a report comparing NVDA to TSLA",
        stream=True,
        show_full_reasoning=True,
    )
