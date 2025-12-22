import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools(), YFinanceTools(cache_results=True)],
)

asyncio.run(
    agent.aprint_response(
        "What is the current stock price of AAPL and latest news on 'Apple'?",
        markdown=True,
    )
)
