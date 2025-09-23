from typing import Iterator

from agno.agent import Agent, RunOutputEvent
from agno.models.meta import LlamaOpenAI
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import pprint_run_response
from rich.pretty import pprint

agent = Agent(
    model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    tools=[YFinanceTools()],
    markdown=True,
)

run_stream: Iterator[RunOutputEvent] = agent.run(
    "What is the stock price of NVDA", stream=True
)
pprint_run_response(run_stream, markdown=True)

run_response = agent.get_last_run_output()

# Print metrics per message
if run_response.messages:
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
pprint(run_response.metrics)
# Print the session metrics
print("---" * 5, "Session Metrics", "---" * 5)
pprint(agent.get_session_metrics())
