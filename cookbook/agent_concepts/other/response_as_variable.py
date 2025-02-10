from typing import Iterator  # noqa
from rich.pretty import pprint
from agno.agent import Agent, RunResponse
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools

agent = Agent(
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
)

run_response: RunResponse = agent.run("What is the stock price of NVDA")
pprint(run_response)

# run_response_strem: Iterator[RunResponse] = agent.run("What is the stock price of NVDA", stream=True)
# for response in run_response_strem:
#     pprint(response)
