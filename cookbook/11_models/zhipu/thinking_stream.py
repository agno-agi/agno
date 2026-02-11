"""
Example demonstrating Zhipu's thinking mode with streaming for complex reasoning tasks.
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

# Example with streaming
agent.print_response(
    "Solve this problem step by step: A farmer has chickens and rabbits. "
    "There are 35 heads and 94 feet in total. How many chickens and how many rabbits are there?",
    stream=True,
)
