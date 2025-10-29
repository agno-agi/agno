"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.ibm import WatsonX
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=WatsonX(id="mistralai/mistral-small-3-1-24b-instruct-2503"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
