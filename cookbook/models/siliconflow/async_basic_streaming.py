"""
Basic streaming async example using siliconflow.
"""

import asyncio

from agno.agent import Agent
from agno.models.siliconflow import Siliconflow

agent = Agent(
    model=Siliconflow(id="openai/gpt-oss-120b"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
