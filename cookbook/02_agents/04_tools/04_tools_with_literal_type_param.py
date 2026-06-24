"""
Example demonstrating Literal type support in Agno tools.

This example shows how to use typing.Literal for function parameters
in Agno toolkits and standalone tools. Literal types are useful when
a parameter should only accept specific predefined values.
"""

from typing import Literal

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import Toolkit


class FileOperationsToolkit(Toolkit):
    """A toolkit demonstrating Literal type parameters."""

    def __init__(self):
        super().__init__(name="file_operations", tools=[self.manage_file])

    def manage_file(
        self,
        filename: str,
        operation: Literal["create", "read", "update", "delete"] = "read",
        priority: Literal["low", "medium", "high"] = "medium",
    ) -> str:
        """
        Manage a file with the specified operation.

        Args:
            filename: The name of the file to operate on.
            operation: The operation to perform on the file.
            priority: The priority level for this operation.

        Returns:
            A message describing what was done.
        """
        return f"Performed '{operation}' on '{filename}' with {priority} priority"


def standalone_tool(
    action: Literal["start", "stop", "restart"],
    service_name: str,
) -> str:
    """
    Control a service with the specified action.

    Args:
        action: The action to perform on the service.
        service_name: The name of the service to control.

    Returns:
        A message describing the action taken.
    """
    return f"Service '{service_name}' has been {action}ed"


def main():
    # Create an agent with both toolkit and standalone tool
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[FileOperationsToolkit(), standalone_tool],
        instructions="You are a helpful assistant that can manage files and services.",
        markdown=True,
    )

    # Test with file operations
    print("Testing file operations with Literal types:")
    agent.print_response(
        "Create a new file called 'report.txt' with high priority", stream=True
    )

    print("\n" + "=" * 50 + "\n")

    # Test with service control
    print("Testing service control with Literal types:")
    agent.print_response("Restart the web server service", stream=True)


if __name__ == "__main__":
    main()
