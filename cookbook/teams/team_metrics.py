from typing import Iterator

from agno.agent import Agent, RunResponse
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import pprint_run_response
from rich.pretty import pprint

stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools()],
)


team = Team(
    name="Stock Research Team",
    mode="route",
    model=OpenAIChat("gpt-4o"),
    members=[stock_searcher],
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
)


run_stream: Iterator[RunResponse] = team.run(
    "What is the stock price of NVDA", stream=True
)
pprint_run_response(run_stream, markdown=True)


print("---" * 5, "Team Leader Message Metrics", "---" * 5)
# Print metrics per message for lead agent
if team.run_response.messages:
    for message in team.run_response.messages:
        if message.role == "assistant":
            if message.content:
                print(f"Message: {message.content}")
            elif message.tool_calls:
                print(f"Tool calls: {message.tool_calls}")
            print("---" * 5, "Metrics", "---" * 5)
            pprint(message.metrics)
            print("---" * 20)


# Print the metrics
print("---" * 5, "Aggregated Metrics of Team Agent", "---" * 5)
pprint(team.run_response.metrics)

# Print the session metrics
print("---" * 5, "Session Metrics", "---" * 5)
pprint(team.session_metrics)


print("---" * 5, "Team Member Message Metrics", "---" * 5)
# Print metrics per member per message
if team.run_response.member_responses:
    for member_response in team.run_response.member_responses:
        if member_response.messages:
            for message in member_response.messages:
                if message.role == "assistant":
                    if message.content:
                        print(f"Message: {message.content}")
                    elif message.tool_calls:
                        print(f"Tool calls: {message.tool_calls}")
                    print("---" * 5, "Metrics", "---" * 5)
                    pprint(message.metrics)
                    print("---" * 20)


# Print the session metrics
print("---" * 5, "Full Team Session Metrics", "---" * 5)
pprint(team.full_team_session_metrics)
