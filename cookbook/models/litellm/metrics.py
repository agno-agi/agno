from agno.agent import Agent
from agno.models.litellm import LiteLLM
from agno.tools.yfinance import YFinanceTools
from rich.pretty import pprint

agent = Agent(
    model=LiteLLM(
        id="gpt-4o",
    ),
    tools=[YFinanceTools(stock_price=True)],
    markdown=True,
    show_tool_calls=True,
)

agent.print_response("What is the stock price of NVDA", stream=True)

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

# Print the aggregated metrics for the whole run
print("---" * 5, "Collected Metrics", "---" * 5)
pprint(agent.run_response.metrics)
# Print the aggregated metrics for the whole session
print("---" * 5, "Session Metrics", "---" * 5)
pprint(agent.session_metrics)
