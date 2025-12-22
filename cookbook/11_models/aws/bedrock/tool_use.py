"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.aws import AwsBedrock
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=AwsBedrock(id="mistral.mistral-large-2402-v1:0"),
    tools=[WebSearchTools()],
    instructions="You are a helpful assistant that can use the following tools to answer questions.",
    markdown=True,
)
agent.print_response("Whats happening in France?")
