"""
Openai Verbosity Control
========================

Cookbook example for `openai/responses/verbosity_control.py`.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="gpt-5", verbosity="high"),
    tools=[YFinanceTools()],
    instructions="Use tables to display data.",
    markdown=True,
)
agent.print_response("Write a report comparing NVDA to TSLA", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
