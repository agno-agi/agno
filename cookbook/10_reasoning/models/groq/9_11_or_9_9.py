"""
9.11 vs 9.9 Comparison
======================

Demonstrates Groq with a reasoning model for numeric comparison.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.groq import Groq

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Groq(
        id="qwen/qwen3.6-27b",
        temperature=0.6,
        max_tokens=1024,
        top_p=0.95,
    ),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "9.11 and 9.9 -- which is bigger?",
        stream=True,
        show_full_reasoning=True,
    )
