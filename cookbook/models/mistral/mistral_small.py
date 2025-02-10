"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.mistral import MistralChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=MistralChat(id="mistral-small-latest"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Tell me about mistrall small, any news", stream=True)
