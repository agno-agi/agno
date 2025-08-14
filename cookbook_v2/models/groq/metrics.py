from typing import Iterator

from agno.agent import Agent, RunOutputEvent
from agno.models.groq import Groq
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import pprint_run_response
from rich.pretty import pprint

agent = Agent(
    model=Groq(id="llama-3.3-70b-versatile"),
    tools=[YFinanceTools(stock_price=True)],
    markdown=True,
)

run_stream: Iterator[RunOutputEvent] = agent.run(
    "What is the stock price of NVDA", stream=True
)
pprint_run_response(run_stream, markdown=True)

# Print metrics per message
if agent.run_response and agent.run_response.messages:
    for message in agent.run_response.messages:  # type: ignore
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
pprint(agent.run_response.metrics)  # type: ignore
# Print the session metrics
print("---" * 5, "Session Metrics", "---" * 5)
pprint(agent.session_metrics)
