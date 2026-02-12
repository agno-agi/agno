"""
Openai Tool Use Gpt 5
=====================

Cookbook example for `openai/responses/tool_use_gpt_5.py`.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5"),
    tools=[YFinanceTools(cache_results=True)],
    markdown=True,
    telemetry=False,
)

agent.print_response("What is the current price of TSLA?", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
