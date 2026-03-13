"""
VLLM Reasoning Agent
====================

Demonstrates native reasoning model support with vLLM.

Requires a vLLM server running a reasoning-capable model (QwQ, Qwen3, DeepSeek-R1, etc.).
Start vLLM with: vllm serve Qwen/QwQ-32B --enable-reasoning --reasoning-parser deepseek_r1

Set environment variables:
    VLLM_API_KEY=your-key
    VLLM_BASE_URL=http://localhost:8000/v1/
"""

from agno.agent import Agent
from agno.models.vllm import VLLM

# ---------------------------------------------------------------------------
# Create Agent — enable_thinking tells Agno this is a native reasoning model
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What is 23 x 47? Show your step-by-step reasoning.",
        stream=True,
        show_full_reasoning=True,
    )
