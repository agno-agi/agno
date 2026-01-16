"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.mistral import MistralChat
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=MistralChat(
        id="mistral-large-latest",
    ),
    tools=[WebSearchTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?", stream=True)
