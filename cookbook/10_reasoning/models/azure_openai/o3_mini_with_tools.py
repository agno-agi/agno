from agno.agent import Agent
from agno.models.azure.openai_chat import AzureOpenAI
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=AzureOpenAI(id="o3-mini"),
    tools=[YFinanceTools()],
    instructions="Use tables to display data.",
    markdown=True,
)
agent.print_response("Write a report comparing NVDA to TSLA", stream=True)
