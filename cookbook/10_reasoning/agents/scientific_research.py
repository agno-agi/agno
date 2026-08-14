"""
Scientific Abstract Critique
============================

Demonstrates DeepSeek-backed reasoning for methodology critique.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
task = (
    "Read the following abstract of a scientific paper and provide a critical evaluation of its methodology,"
    "results, conclusions, and any potential biases or flaws:\n\n"
    "Abstract: This study examines the effect of a new teaching method on student performance in mathematics. "
    "A sample of 30 students was selected from a single school and taught using the new method over one semester. "
    "The results showed a 15% increase in test scores compared to the previous semester. "
    "The study concludes that the new teaching method is effective in improving mathematical performance among high school students."
)

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
