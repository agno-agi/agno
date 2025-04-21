"""🤝 Human-in-the-Loop: Adding User Confirmation to Tool Calls

This example shows how to implement human-in-the-loop functionality in your Agno tools.
It shows how to:
- Add pre-hooks to tools for user confirmation
- Handle user input during tool execution
- Gracefully cancel operations based on user choice

Some practical applications:
- Confirming sensitive operations before execution
- Reviewing API calls before they're made
- Validating data transformations
- Approving automated actions in critical systems

Run `pip install openai httpx rich agno` to install dependencies.
"""

import subprocess

from agno.run.response import RunEvent
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import tool


def _execute_shell_command(command: str) -> str:
    if command.startswith("ls"):
        return subprocess.check_output(command, shell=True).decode("utf-8")
    else:
        raise Exception(f"Unsupported command: {command}")



@tool(external_execution=True)
def execute_shell_command(command: str) -> str:
    """Execute a shell command.

    Args:
        command (str): The shell command to execute

    Returns:
        str: The output of the shell command
    """
    pass


# Initialize the agent with a tech-savvy personality and clear instructions
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[execute_shell_command],
    markdown=True,
)

run_response = agent.run("What files do I have in my current directory?")
if run_response.event == RunEvent.tool_call_confirmation_required.value:
    print(run_response.tools)
    user_input = input("Do you want to proceed? (y/n)")
    if user_input == "y":
        agent.continue_run()
