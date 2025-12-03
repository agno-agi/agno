"""🤝 Human-in-the-Loop with OpenAI Responses API (gpt-4.1-mini)

This example mirrors the external tool execution async example but uses
OpenAIResponses with gpt-4.1-mini to validate tool-call id handling.

Run `pip install openai agno` to install dependencies.
"""

import asyncio
import subprocess

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools import tool
from agno.utils import pprint


# We have to create a tool with the correct name, arguments and docstring
# for the agent to know what to call.
@tool(external_execution=True)
def execute_shell_command(command: str) -> str:
    """Execute a shell command.

    Args:
        command (str): The shell command to execute

    Returns:
        str: The output of the shell command
    """
    if (
        command.startswith("ls ")
        or command == "ls"
        or command.startswith("cat ")
        or command.startswith("head ")
    ):
        return subprocess.check_output(command, shell=True).decode("utf-8")
    raise Exception(f"Unsupported command: {command}")


agent = Agent(
    model=OpenAIResponses(id="gpt-4.1-mini"),
    tools=[execute_shell_command],
    markdown=True,
    db=SqliteDb(session_table="test_session", db_file="tmp/example.db"),
)

run_response = asyncio.run(agent.arun("What files do I have in my current directory?"))

# Keep executing externally-required tools until the run completes
for requirement in run_response.active_requirements:
    if requirement.needs_external_execution:
        if requirement.tool_execution.tool_name == execute_shell_command.name:
            print(
                f"Executing {requirement.tool_execution.tool_name} with args {requirement.tool_execution.tool_args} externally"
            )
            result = execute_shell_command.entrypoint(
                **requirement.tool_execution.tool_args
            )  # type: ignore
            requirement.set_external_execution_result(result)
        else:
            print(
                f"Skipping unsupported external tool: {requirement.tool_execution.tool_name}"
            )

run_response = asyncio.run(
    agent.acontinue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )
)
pprint.pprint_run_response(run_response)


# Or for simple debug flow
# agent.print_response("What files do I have in my current directory?")
