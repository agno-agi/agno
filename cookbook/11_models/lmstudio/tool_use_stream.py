"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.lmstudio import LMStudio
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=LMStudio(id="qwen2.5-7b-instruct-1m"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
