"""This example shows how to get reasoning summaries with our OpenAIResponses model.
Useful for contexts where a long reasoning process is relevant and directly relevant to the user."""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools

# Setup the reasoning Agent
agent = Agent(
    model=OpenAIResponses(
        id="o4-mini",
        reasoning_summary="auto",  # Requesting a reasoning summary
    ),
    tools=[YFinanceTools(stock_price=True, analyst_recommendations=True)],
    instructions="Use tables to display the analysis",
    show_tool_calls=True,
    markdown=True,
)

agent.print_response(
    "Write a brief report comparing NVDA to TSLA",
    stream=True,
    stream_intermediate_steps=True,
)
