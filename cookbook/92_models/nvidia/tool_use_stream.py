"""Run `uv pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.nvidia import Nvidia
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Nvidia(id="meta/llama-3.3-70b-instruct"),
    tools=[WebSearchTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?", stream=True)
