"""
Example showing how to use stop_after_tool_call_tools parameter in a Toolkit.

This demonstrates using stop_after_tool_call_tools without the @tool decorator,
which is the recommended approach for class methods that need to stop the agent
after execution.
"""

from agno.agent import Agent
from agno.tools import Toolkit


class SimpleToolkit(Toolkit):
    """Simple toolkit demonstrating stop_after_tool_call_tools."""

    def __init__(self):
        self.counter = 0
        Toolkit.__init__(
            self,
            name="simple_toolkit",
            tools=[
                self.increment_and_stop,
                self.increment_continue,
                self.get_counter,
            ],
            stop_after_tool_call_tools=["increment_and_stop"],
        )

    def increment_and_stop(self) -> str:
        """
        Increment counter and stop. Agent should NOT continue after this.

        Returns:
            Message with new counter value
        """
        self.counter += 10
        return f"Counter incremented to {self.counter}. Agent should stop here!"

    def increment_continue(self) -> str:
        """
        Increment counter but allow agent to continue.

        Returns:
            Message with new counter value
        """
        self.counter += 1
        return f"Counter incremented to {self.counter}. Agent can continue."

    def get_counter(self) -> str:
        """
        Get current counter value.

        Returns:
            Current counter value
        """
        return f"Current counter value: {self.counter}"


if __name__ == "__main__":
    toolkit = SimpleToolkit()

    print("Registered functions:")
    for name, func in toolkit.functions.items():
        print(f"  {name}:")
        print(f"    stop_after_tool_call = {func.stop_after_tool_call}")
        print(f"    show_result = {func.show_result}")

    # Verify the flag is set correctly
    assert toolkit.functions["increment_and_stop"].stop_after_tool_call is True
    assert toolkit.functions["increment_continue"].stop_after_tool_call is False
    assert toolkit.functions["get_counter"].stop_after_tool_call is False

    agent = Agent(
        tools=[toolkit],
        markdown=True,
    )

    agent.print_response(
        "Call the increment_and_stop tool once. Do not call any other tools."
    )
