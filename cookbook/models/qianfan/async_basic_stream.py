"""
Basic streaming async example using Qianfan.
"""

import asyncio

from agno.agent import Agent
from agno.models.qianfan import Qianfan

agent = Agent(model=Qianfan(id="deepseek-v3"), markdown=True)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
