import asyncio

from agno.agent import Agent
from agno.models.litellm import LiteLLM
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=LiteLLM(
        id="gpt-4o",
        name="LiteLLM",
    ),
    markdown=True,
    tools=[DuckDuckGoTools()],
)

# Ask a question that would likely trigger tool use
asyncio.run(agent.aprint_response("What is happening in France?"))
