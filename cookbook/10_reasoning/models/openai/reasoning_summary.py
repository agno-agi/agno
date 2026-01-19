"""This example shows how to get reasoning summaries with our OpenAIResponses model.
Useful for contexts where a long reasoning process is relevant and directly relevant to the user."""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools

# Setup the reasoning Agent
agent = Agent(
    model=OpenAIResponses(
        id="o4-mini",
        reasoning_summary="auto",  # Requesting a reasoning summary
    ),
    tools=[DuckDuckGoTools(enable_search=True)],
    instructions="Use tables to display the analysis",
    markdown=True,
)

agent.print_response(
    "Write a brief report comparing NVDA to TSLA",
    stream=True,
)
