import asyncio

from agno.agent import Agent
from agno.models.litellm import LiteLLM
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=LiteLLM(
        id="gpt-4o",
        name="LiteLLM",
    ),
    markdown=True,
    tools=[WebSearchTools()],
)

# Ask a question that would likely trigger tool use
asyncio.run(agent.aprint_response("What is happening in France?"))
