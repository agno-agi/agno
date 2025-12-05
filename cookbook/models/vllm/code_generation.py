"""Code generation example with DeepSeek-Coder.
Run vLLM model: vllm serve deepseek-ai/deepseek-coder-6.7b-instruct \
        --dtype float32 \
        --tool-call-parser pythonic
"""

from agno.agent import Agent
from agno.models.vllm import VLLM

agent = Agent(
    model=VLLM(id="deepseek-ai/deepseek-coder-6.7b-instruct"),
    description="You are an expert Python developer.",
    markdown=True,
)

agent.print_response(
    "Write a Python function that returns the nth Fibonacci number using dynamic programming."
)
