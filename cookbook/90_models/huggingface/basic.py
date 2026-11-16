"""
Huggingface Basic
=================

Cookbook example for `huggingface/basic.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.huggingface import HuggingFace

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=HuggingFace(id="openai/gpt-oss-120b", max_tokens=4096, temperature=0),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response(
        "What is meaning of life and then recommend 5 best books to read about it"
    )

    # --- Sync + Streaming ---
    agent.print_response(
        "What is meaning of life and then recommend 5 best books to read about it",
        stream=True,
    )

    # --- Async ---
    asyncio.run(
        agent.aprint_response(
            "What is meaning of life and then recommend 5 best books to read about it"
        )
    )

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response(
            "What is meaning of life and then recommend 5 best books to read about it",
            stream=True,
        )
    )
