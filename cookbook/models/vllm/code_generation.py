"""Code generation example with DeepSeek-Coder.
Requires no gated access. If you haven't downloaded the model before, vLLM will
pull it automatically (≈7 GB fp32).

Run vLLM:

    vllm serve deepseek-ai/deepseek-coder-6.7b-instruct \
        --dtype float32 \
        --tool-call-parser pythonic   # DeepSeek follows the same style

Then execute this script.
"""

from agno.agent import Agent
from agno.models.vllm import Vllm

authoring_agent = Agent(
    model=Vllm(id="deepseek-ai/deepseek-coder-6.7b-instruct"),
    description="You are an expert Python developer.",
    markdown=True,
)

authoring_agent.print_response(
    "Write a Python function that returns the nth Fibonacci number using dynamic programming."
)
