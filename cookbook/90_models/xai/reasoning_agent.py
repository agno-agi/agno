"""
Xai Reasoning Agent
===================

Cookbook example for `xai/reasoning_agent.py`.
"""

from agno.agent import Agent
from agno.models.xai import xAI
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

reasoning_agent = Agent(
    model=xAI(id="grok-3-beta"),
    tools=[
        ReasoningTools(add_instructions=True, add_few_shot=True),
        YFinanceTools(),
    ],
    instructions=[
        "Use tables to display data",
        "Only output the report, no other text",
    ],
    markdown=True,
)
reasoning_agent.print_response(
    "Write a report on TSLA",
    stream=True,
    show_full_reasoning=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
