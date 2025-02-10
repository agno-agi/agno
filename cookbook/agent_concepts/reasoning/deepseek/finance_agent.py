from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        )
    ],
    instructions=["Use tables where possible"],
    show_tool_calls=True,
    markdown=True,
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
)
reasoning_agent.print_response("Write a report comparing NVDA to TSLA", stream=True)
