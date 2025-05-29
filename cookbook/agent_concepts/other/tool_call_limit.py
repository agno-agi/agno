"""
This cookbook shows how to use tool call limit to control the number of tool calls an agent can make.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=Claude(id="claude-3-5-haiku-20241022"),
    tools=[YFinanceTools(company_news=True, cache_results=True)],
    tool_call_limit=1,
)

# It should only call the first tool and fail to call the second tool.
agent.print_response(
    "Find me the current price of TSLA, then after that find me the latest news about Tesla.",
    stream=True,
)
