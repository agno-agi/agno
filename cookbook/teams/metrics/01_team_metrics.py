"""
This example demonstrates how to access and analyze team metrics.

Shows how to retrieve detailed metrics for team execution, including
message-level metrics, session metrics, and member-specific metrics.
"""

from typing import Iterator

from agno.agent import Agent, RunOutput
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import pprint_run_response
from rich.pretty import pprint

# Create stock research agent
stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools()],
)

# Create team with metrics tracking enabled
team = Team(
    name="Stock Research Team",
    mode="route",
    model=OpenAIChat("gpt-4o"),
    members=[stock_searcher],
    markdown=True,
    debug_mode=True,  # Enable detailed metrics tracking
    show_members_responses=True,
)

# Run the team and capture metrics
run_stream: Iterator[RunOutput] = team.run(
    "What is the stock price of NVDA", stream=True
)
pprint_run_response(run_stream, markdown=True)

# Analyze team leader message metrics
print("=" * 50)
print("TEAM LEADER MESSAGE METRICS")
print("=" * 50)

if team.run_response.messages:
    for message in team.run_response.messages:
        if message.role == "assistant":
            if message.content:
                print(f"📝 Message: {message.content[:100]}...")
            elif message.tool_calls:
                print(f"🔧 Tool calls: {message.tool_calls}")

            print("-" * 30, "Metrics", "-" * 30)
            pprint(message.metrics)
            print("-" * 70)

# Analyze aggregated team metrics
print("=" * 50)
print("AGGREGATED TEAM METRICS")
print("=" * 50)
pprint(team.run_response.metrics)

# Analyze session-level metrics
print("=" * 50)
print("SESSION METRICS")
print("=" * 50)
pprint(team.session_metrics)

# Analyze individual member metrics
print("=" * 50)
print("TEAM MEMBER MESSAGE METRICS")
print("=" * 50)

if team.run_response.member_responses:
    for member_response in team.run_response.member_responses:
        if member_response.messages:
            for message in member_response.messages:
                if message.role == "assistant":
                    if message.content:
                        print(f"📝 Member Message: {message.content[:100]}...")
                    elif message.tool_calls:
                        print(f"🔧 Member Tool calls: {message.tool_calls}")

                    print("-" * 20, "Member Metrics", "-" * 20)
                    pprint(message.metrics)
                    print("-" * 60)

# Full team session metrics (comprehensive view)
print("=" * 50)
print("FULL TEAM SESSION METRICS")
print("=" * 50)
pprint(team.full_team_session_metrics)
