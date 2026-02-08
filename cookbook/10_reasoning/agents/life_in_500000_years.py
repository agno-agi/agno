"""
Future Life Storytelling
========================

Demonstrates built-in and DeepSeek-backed reasoning for speculative writing.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
task = "Write a short story about life in 500000 years"

cot_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)

deepseek_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Built-in Chain Of Thought ===")
    cot_agent.print_response(task, stream=True, show_full_reasoning=True)

    print("\n=== DeepSeek Reasoning Model ===")
    deepseek_agent.print_response(task, stream=True, show_full_reasoning=True)
