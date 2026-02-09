"""Team HITL: Member agent tool with external execution.

This example demonstrates how a team pauses when a member agent's tool
requires external execution. The tool result is provided by the caller
rather than being executed by the agent.
"""

import subprocess

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools import tool


@tool(external_execution=True)
def run_shell_command(command: str) -> str:
    """Execute a shell command on the server.

    Args:
        command (str): The shell command to execute
    """
    return subprocess.check_output(command, shell=True).decode("utf-8")


ops_agent = Agent(
    name="Ops Agent",
    role="Handles server operations",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[run_shell_command],
)

team = Team(
    name="SRE Team",
    members=[ops_agent],
    model=OpenAIChat(id="gpt-4o-mini"),
)

response = team.run("List the files in the current directory")

if response.is_paused:
    print("Team paused - requires external execution")
    for req in response.requirements:
        if req.needs_external_execution:
            print(f"  Tool: {req.tool_execution.tool_name}")
            print(f"  Args: {req.tool_execution.tool_args}")

            # Execute the tool externally
            result = run_shell_command.entrypoint(**req.tool_execution.tool_args)
            req.set_external_execution_result(result)

    response = team.continue_run(response)
    print(f"Result: {response.content}")
else:
    print(f"Result: {response.content}")
