from typing import Generator

from agno.agent import Agent
from agno.tools import Toolkit, tool


class MyToolkit(Toolkit):
    def __init__(self, multiplier: int = 2):
        """Initialize the toolkit with a configurable multiplier."""
        self.multiplier = multiplier

        # Initialize Toolkit with the decorated methods
        # The @tool decorator creates Function objects that will be properly bound to self
        super().__init__(
            name="my_toolkit",
            tools=[
                self.multiply_number,
                self.get_greeting,
            ],
        )

    @tool(stop_after_tool_call=True)
    def multiply_number(self, number: int) -> int:
        """
        Multiply a number by the toolkit's multiplier.
        Args:
            number: The number to multiply
        Returns:
            The multiplied result
        """
        return number * self.multiplier

    @tool()
    def get_greeting(self, name: str) -> str:
        """
        Get a greeting message.
        Args:
            name: The name to greet
        Returns:
            A greeting message
        """
        return f"Hello, {name}! The multiplier is {self.multiplier}."


class ToolkitWithGenerator(Toolkit):
    """Example toolkit with a generator method."""

    def __init__(self):
        super().__init__(
            name="generator_toolkit",
            tools=[self.stream_numbers],
        )

    @tool(stop_after_tool_call=True)
    def stream_numbers(self, count: int) -> Generator[str, None, None]:
        """
        Stream numbers from 1 to count.
        Args:
            count: How many numbers to stream
        Returns:
            A generator yielding numbers
        """
        for i in range(1, count + 1):
            yield f"Number: {i}"


if __name__ == "__main__":
    # Create toolkit with custom multiplier
    toolkit = MyToolkit(multiplier=5)

    # Verify the functions are registered correctly
    print("Registered functions:")
    for name, func in toolkit.functions.items():
        print(
            f"  {name}: stop_after_tool_call={func.stop_after_tool_call}, show_result={func.show_result}"
        )

    # Create agent with the toolkit
    agent = Agent(
        tools=[toolkit],
        markdown=True,
    )

    # Test the multiply_number tool (should stop after tool call)
    print("\n--- Testing multiply_number (stop_after_tool_call=True) ---")
    agent.print_response("What is 7 multiplied by the multiplier?")

    # Test the get_greeting tool
    print("\n--- Testing get_greeting ---")
    agent.print_response("Greet me, my name is Alice")
