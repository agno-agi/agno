"""
Toolkit Per-Tool Instructions
=============================

Demonstrates @tool(instructions=...) works both as a bare function
and inside a Toolkit.

Previously, per-tool instructions were silently dropped when tools
were registered via a Toolkit. This cookbook verifies both paths
now work correctly.
"""

from agno.agent import Agent
from agno.agent._tools import parse_tools
from agno.models.openai import OpenAIResponses
from agno.tools import Toolkit, tool
from unittest.mock import MagicMock


# Path 1: Bare function with instructions
@tool(instructions="Always explain your reasoning when subtracting.")
def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


# Path 2: Toolkit with per-tool instructions
class MathToolkit(Toolkit):
    def __init__(self):
        super().__init__(name="math_toolkit", tools=[self.add, self.multiply])

    @tool(instructions="Always show your work step-by-step when adding numbers.")
    def add(self, a: int, b: int) -> int:
        """Add two numbers together."""
        return a + b

    @tool(instructions="When multiplying, mention if the result is even or odd.")
    def multiply(self, a: int, b: int) -> int:
        """Multiply two numbers together."""
        return a * b


if __name__ == "__main__":
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=[subtract, MathToolkit()],
    )

    # Trigger tool parsing to populate _tool_instructions
    mock_model = MagicMock()
    mock_model.supports_native_structured_outputs = False
    parse_tools(agent=agent, tools=agent.tools, model=mock_model)

    # Inspect what instructions reached the agent
    print("=" * 70)
    print("INSPECTING: agent._tool_instructions")
    print("=" * 70)
    for i, instruction in enumerate(agent._tool_instructions, 1):
        print(f"\n[{i}] {instruction}")
    print("\n" + "=" * 70)

    expected_count = 3  # 1 bare function + 2 from toolkit
    if len(agent._tool_instructions) == expected_count:
        print(f"SUCCESS: All {expected_count} per-tool instructions captured")
        print("  - 1 from bare function (subtract)")
        print("  - 2 from Toolkit (add, multiply)")
    else:
        print(f"FAILURE: Expected {expected_count}, got {len(agent._tool_instructions)}")
