"""
Example showing stop_after_tool_call_tools with dual inheritance.

This demonstrates that stop_after_tool_call_tools works correctly even when
the Toolkit class uses multiple inheritance.
"""

from agno.agent import Agent
from agno.tools import Toolkit


class BaseConfig:
    """Base configuration class for dual inheritance."""

    def __init__(self, render_type: str = "OBJECT"):
        self._render_type = render_type


class DualInheritanceToolkit(Toolkit, BaseConfig):
    """Toolkit with dual inheritance - simulating the user's case."""

    def __init__(self, render_type: str = "JSON"):
        # Initialize base class first
        BaseConfig.__init__(self, render_type)

        # Then initialize Toolkit
        Toolkit.__init__(
            self,
            name="dual_inheritance_toolkit",
            tools=[self.filter_changed, self.get_render_type],
            stop_after_tool_call_tools=["filter_changed"],
        )

    def filter_changed(self, session_state) -> str:
        """
        Handle filter change event. Should stop after this tool call.

        Args:
            session_state: The session state (injected automatically)

        Returns:
            Message indicating filter changed
        """
        return (
            f"Filter changed! Render type: {self._render_type}. Agent should stop here!"
        )

    def get_render_type(self) -> str:
        """
        Get the current render type.

        Returns:
            Current render type
        """
        return f"Current render type: {self._render_type}"


if __name__ == "__main__":
    toolkit = DualInheritanceToolkit(render_type="CUSTOM")

    print("Registered functions:")
    for name, func in toolkit.functions.items():
        print(f"  {name}:")
        print(f"    stop_after_tool_call = {func.stop_after_tool_call}")
        print(f"    show_result = {func.show_result}")

    # Verify the flag is set correctly
    assert toolkit.functions["filter_changed"].stop_after_tool_call is True
    assert toolkit.functions["get_render_type"].stop_after_tool_call is False

    agent = Agent(
        tools=[toolkit],
        markdown=True,
    )

    agent.print_response("Call the filter_changed tool.")
