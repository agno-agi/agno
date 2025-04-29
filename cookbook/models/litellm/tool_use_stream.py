"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.litellm import LiteLLM
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=LiteLLM(
        id="gpt-4o",
        name="LiteLLM",
    ),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)

# Ask a question that would likely trigger tool use
agent.print_response("Whats happening in France?", stream=True)
