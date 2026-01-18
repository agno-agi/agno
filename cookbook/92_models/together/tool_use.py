"""Run `uv pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.together import Together
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Together(id="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?")
