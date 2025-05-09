import asyncio

from agno.agent import Agent
from agno.models.cerebras import CerebrasOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=CerebrasOpenAI(id="llama-3.3-70b"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?"))
