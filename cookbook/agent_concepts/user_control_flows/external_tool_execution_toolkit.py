"""🤝 Human-in-the-Loop: Execute a tool call outside of the agent

This example shows how to implement human-in-the-loop functionality in your Agno tools.
It shows how to:
- Use external tool execution to execute a tool call outside of the agent

Run `pip install openai agno` to install dependencies.
"""

import subprocess

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import tool
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
)

run_response = agent.run("What files do I have in my current directory?")
if run_response.is_paused:  # Or agent.run_response.is_paused
    for tool in run_response.tools_awaiting_external_execution:
        if tool.tool_name == "list_dir":
            print(f"Executing {tool.tool_name} with args {tool.tool_args} externally")
            # We execute the tool ourselves. You can also execute something completely external here.
            result = tools.list_dir(**tool.tool_args)
            # We have to set the result on the tool execution object so that the agent can continue
            tool.result = result

    run_response = agent.continue_run()
    pprint.pprint_run_response(run_response)
