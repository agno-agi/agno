from agno.agent import Agent
from agno.models.vllm import vLLM

agent = Agent(
    model=vLLM(id="Qwen/Qwen2.5-7B-Instruct", top_k=20, enable_thinking=False),
    markdown=True,
)
agent.print_response("Share a 2 sentence horror story", stream=True)
