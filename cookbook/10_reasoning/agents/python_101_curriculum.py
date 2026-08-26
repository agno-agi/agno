"""
Python 101 Curriculum Planning
==============================

Demonstrates DeepSeek-backed reasoning for curriculum design.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
task = "Craft a curriculum for Python 101"

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
