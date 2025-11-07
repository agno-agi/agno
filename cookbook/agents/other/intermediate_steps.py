from typing import Iterator

from agno.agent import Agent, RunOutputEvent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from rich.pretty import pprint

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
    markdown=True,
)

run_stream: Iterator[RunOutputEvent] = agent.run(
    "What is the stock price of NVDA", stream=True, stream_events=True
)
for chunk in run_stream:
    pprint(chunk.to_dict())
    print("---" * 20)
