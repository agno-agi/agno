"""🔇 External Tool Execution: Silent vs Verbose

This example shows the difference between silent and non-silent external tools.
- Non-silent (default): Agent prints "I have tools to execute..." messages
- Silent: No verbose messages, cleaner output for production UX

Run `pip install openai agno` to install dependencies.
"""

import subprocess

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import tool
from agno.utils import pprint


# Non-silent tool: will print "I have tools to execute..." when paused
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


# Silent tool: no verbose messages, ideal for frontend-rendered components
@tool(external_execution=True, silent=True)
def render_file_tree(files: list[str]) -> str:
    """Render a file tree visualization in the frontend.

    Args:
        files (list[str]): List of file paths to display

    Returns:
        str: Confirmation that the tree was rendered
    """
    return "File tree rendered in frontend"


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[execute_shell_command, render_file_tree],
    markdown=True,
    db=SqliteDb(session_table="test_session", db_file="tmp/example.db"),
)

run_response = agent.run("What files do I have in my current directory? Then show me a tree view.")

if run_response.is_paused:
    for requirement in run_response.active_requirements:
        if requirement.needs_external_execution:
            tool_name = requirement.tool_execution.tool_name
            tool_args = requirement.tool_execution.tool_args

            if tool_name == execute_shell_command.name:
                print(f"Executing {tool_name} with args {tool_args} externally")
                result = execute_shell_command.entrypoint(**tool_args)  # type: ignore
                requirement.set_external_execution_result(result)

            elif tool_name == render_file_tree.name:
                # Silent tool - no verbose message was printed by the agent
                print(f"Rendering file tree (silent tool)")
                result = render_file_tree.entrypoint(**tool_args)  # type: ignore
                requirement.set_external_execution_result(result)

run_response = agent.continue_run(
    run_id=run_response.run_id,
    requirements=run_response.requirements,
)
pprint.pprint_run_response(run_response)
