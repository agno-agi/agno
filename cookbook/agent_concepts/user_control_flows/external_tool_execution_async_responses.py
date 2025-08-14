"""🤝 Human-in-the-Loop with OpenAI Responses API (gpt-4.1-mini)

This example mirrors the external tool execution async example but uses
OpenAIResponses with gpt-4.1-mini to validate tool-call id handling.

Run `pip install openai agno` to install dependencies.
"""

import asyncio
import subprocess

from agno.agent import Agent
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
    if command.startswith("ls"):
        return subprocess.check_output(command, shell=True).decode("utf-8")
    else:
        raise Exception(f"Unsupported command: {command}")


agent = Agent(
    model=OpenAIResponses(id="gpt-4.1-mini"),
    tools=[execute_shell_command],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
)

run_response = asyncio.run(agent.arun("What files do I have in my current directory?"))
if run_response.is_paused:  # Or agent.run_response.is_paused
    for tool in run_response.tools_awaiting_external_execution:
        if tool.tool_name == execute_shell_command.name:
            print(f"Executing {tool.tool_name} with args {tool.tool_args} externally")
            # We execute the tool ourselves. You can also execute something completely external here.
            result = execute_shell_command.entrypoint(**tool.tool_args)
            # We have to set the result on the tool execution object so that the agent can continue
            tool.result = result

    run_response = asyncio.run(agent.acontinue_run(run_response=run_response))
    pprint.pprint_run_response(run_response)


# Or for simple debug flow
# agent.print_response("What files do I have in my current directory?")


