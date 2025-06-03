import asyncio

from agno.agent import Agent
from agno.models.vllm import vLLMOpenAI

agent = Agent(model=vLLMOpenAI(id="microsoft/Phi-3-mini-4k-instruct"), markdown=True)
asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
