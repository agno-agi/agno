"""
Basic async example using Lightning.
"""

import asyncio

from agno.agent import Agent
from agno.models.lightning import Lightning

agent = Agent(model=Lightning(id="openai/gpt-5-nano"), markdown=True)

asyncio.run(agent.aprint_response("Share a 2 sentence comedy story"))
