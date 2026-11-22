"""
Decimal Comparison Reasoning
============================

Demonstrates DeepSeek-backed reasoning for numeric comparison.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
task = "9.11 and 9.9 -- which is bigger?"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(task, stream=True, show_full_reasoning=True)
