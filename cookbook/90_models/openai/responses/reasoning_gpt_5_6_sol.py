"""
Openai Reasoning GPT-5.6 Sol
============================

Cookbook example for `openai/responses/reasoning_gpt_5_6_sol.py`.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-sol"),
    tools=[YFinanceTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Write a report on the NVDA, is it a good buy?", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
