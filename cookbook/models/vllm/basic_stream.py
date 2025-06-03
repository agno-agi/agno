from agno.agent import Agent
from agno.models.vllm import vLLMOpenAI

agent = Agent(
    model=vLLMOpenAI(
        id="microsoft/Phi-3-mini-4k-instruct", top_k=20, enable_thinking=False
    ),
    markdown=True,
)
agent.print_response("Share a 2 sentence horror story", stream=True)
