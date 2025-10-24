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

for i in range(10):
    agent.run("Please call the sample tool")
