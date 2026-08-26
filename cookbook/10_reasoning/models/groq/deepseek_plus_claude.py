"""
Groq Reasoning Plus Claude
==========================

A Groq-hosted reasoning model thinks; Claude writes the answer.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.groq import Groq

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    reasoning_model=Groq(
        id="openai/gpt-oss-120b",
        temperature=0.6,
        max_tokens=1024,
        top_p=0.95,
    ),
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
