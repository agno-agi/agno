from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools(enable_cache=True), YFinanceTools(enable_cache=True)],
    show_tool_calls=True,
    debug_mode=True,
)

agent.print_response("What is the current stock price of AAPL and latest news on 'Apple'?", markdown=True)
