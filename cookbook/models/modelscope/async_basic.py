"""
Basic async example using ModelScope.
"""

import asyncio

from agno.agent import Agent
from agno.models.modelscope import ModelScope

agent = Agent(
    model=ModelScope(id="Qwen/Qwen2.5-7B-Instruct"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Recommend several aerobic exercises suitable for the elderly"))