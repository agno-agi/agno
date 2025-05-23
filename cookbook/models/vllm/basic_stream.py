from agno.agent import Agent
from agno.models.vllm import Vllm

# Make sure a vLLM server is already running (see basic.py)
# Pass stream=True to receive the response incrementally.

agent = Agent(
    model=Vllm(
        id="microsoft/Phi-3-mini-4k-instruct"
    ),  # adjust if your server hosts a different model
    markdown=True,
)

agent.print_response("Share a 2 sentence horror story", stream=True)
