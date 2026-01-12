"""
Example demonstrating Zhipu's thinking mode for complex reasoning tasks.
The thinking mode allows the model to show its reasoning process.
"""

from agno.agent import Agent
from agno.models.zhipu import Zhipu

# Create agent with thinking mode enabled
agent = Agent(
    model=Zhipu(
        id="glm-4.7",
        enable_thinking=True,
    ),
    markdown=True,
)

# Example 1: Mathematical reasoning
print("Example 1: Mathematical Problem")
print("=" * 50)
agent.print_response(
    "Solve this math problem step by step: If a train travels 120 km in 2 hours, "
    "then stops for 30 minutes, and continues at 80 km/h for another hour, "
    "what is the total distance traveled?"
)

print("\n\n")

# Example 2: Logical reasoning
print("Example 2: Logical Puzzle")
print("=" * 50)
agent.print_response(
    "There are three boxes labeled A, B, and C. One contains gold, one contains silver, "
    "and one is empty. Each box has a label, but all labels are wrong. Box A says 'Gold', "
    "Box B says 'Empty', and Box C says 'Silver'. Which box contains what?"
)
