"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.zhipu import Zhipu
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Zhipu(id="glm-4.7"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?")
