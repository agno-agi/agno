"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

def sample_tool(input: str) -> str:
    return f"Sample tool response for {input}"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[sample_tool],
    markdown=True,
)
agent.print_response("Please call the sample tool for the first time")

agent.print_response("Please call the sample tool for the second time")