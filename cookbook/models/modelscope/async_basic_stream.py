"""
Basic streaming async example using modelscope.
"""

import asyncio

from agno.agent import Agent
from agno.models.modelscope import Modelscope

agent = Agent(
    model=Modelscope(id="Qwen/QwQ-32B"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Recommend several aerobic exercises suitable for the elderly", stream=True))