"""🤝 Human-in-the-Loop: Execute a tool call outside of the agent

This example shows how to implement human-in-the-loop functionality in your Agno tools.
It shows how to:
- Use external tool execution to execute a tool call outside of the agent

Run `pip install openai agno` to install dependencies.
"""

import subprocess

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.toolkit import Toolkit
from agno.utils import pprint


class ShellTools(Toolkit):
    def __init__(self, *args, **kwargs):
        super().__init__(
            tools=[self.list_dir],
            external_execution_required_tools=["list_dir"],
            *args,
            **kwargs,
        )

    def list_dir(self, directory: str):
        """
        Lists the contents of a directory.

        Args:
            directory: The directory to list.

        Returns:
            A string containing the contents of the directory.
        """
        return subprocess.check_output(f"ls {directory}", shell=True).decode("utf-8")


tools = ShellTools()

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[tools],
    markdown=True,
    db=SqliteDb(session_table="test_session", db_file="tmp/example.db"),
)

run_response = agent.run("What files do I have in my current directory?")
if run_response.is_paused:
    for requirement in run_response.active_requirements:
        if requirement.needs_external_execution:
            if requirement.tool_execution.tool_name == "list_dir":
                print(
                    f"Executing {requirement.tool_execution.tool_name} with args {requirement.tool_execution.tool_args} externally"
                )
                # We execute the tool ourselves. You can also execute something completely external here.
                result = tools.list_dir(**requirement.tool_execution.tool_args)  # type: ignore
                # We have to set the result on the tool execution object so that the agent can continue
                requirement.set_external_execution_result(result)

    run_response = agent.continue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )
    pprint.pprint_run_response(run_response)
