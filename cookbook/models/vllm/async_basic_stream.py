import asyncio

from agno.agent import Agent
from agno.models.vllm import Vllm

agent = Agent(
    model=Vllm(id="Qwen/Qwen3-8B-FP8", top_k=20, enable_thinking=False), markdown=True
)
asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
