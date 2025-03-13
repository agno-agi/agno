from typing import Iterator

from agno.agent import Agent, RunResponse
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import pprint_run_response
from rich.pretty import pprint

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools(stock_price=True)],
    markdown=True,
    show_tool_calls=True,
)

run_stream: Iterator[RunResponse] = agent.run(
    "What is the stock price of NVDA", stream=True
)
pprint_run_response(run_stream, markdown=True)

# Print metrics per message
if agent.run_response.messages:
    for message in agent.run_response.messages:
        if message.role == "assistant":
            if message.content:
                print(f"Message: {message.content}")
            elif message.tool_calls:
                print(f"Tool calls: {message.tool_calls}")
            print("---" * 5, "Metrics", "---" * 5)
            pprint(message.metrics)
            print("---" * 20)

# Print the metrics
print("---" * 5, "Collected Metrics", "---" * 5)
pprint(agent.run_response.metrics)
# Print the session metrics
print("---" * 5, "Session Metrics", "---" * 5)
pprint(agent.session_metrics)
