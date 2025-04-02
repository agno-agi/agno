import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools(cache_results=True), YFinanceTools(cache_results=True)],
    show_tool_calls=True,
    debug_mode=True,
)

asyncio.run(
    agent.aprint_response(
        "What is the current stock price of AAPL and latest news on 'Apple'?",
        markdown=True,
    )
)
