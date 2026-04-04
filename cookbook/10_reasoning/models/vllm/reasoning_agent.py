from agno.agent import Agent
from agno.models.vllm import VLLM

agent = Agent(
    model=VLLM(
        id="Qwen/QwQ-32B",
        enable_thinking=True,
    ),
    reasoning_model=VLLM(
        id="Qwen/QwQ-32B",
        enable_thinking=True,
    ),
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "What is 23 x 47? Show your step-by-step reasoning.",
        stream=True,
        show_full_reasoning=True,
    )
