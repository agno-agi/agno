from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
    instructions=["Use tables where possible"],
    markdown=True,
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
)
reasoning_agent.print_response("Write a report comparing NVDA to TSLA", stream=True)
