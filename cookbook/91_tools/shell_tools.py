"""
Shell Tools
=============================

Demonstrates shell tools.

``run_shell_command`` executes an arbitrary command on the host OS. Under prompt
injection that makes the agent an RCE sink, so this example gates the tool behind
human-in-the-loop confirmation using the toolkit's ``requires_confirmation_tools``.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.shell import ShellTools

# ---------------------------------------------------------------------------
# Create Agent
#
# requires_confirmation_tools marks run_shell_command as needing human approval,
# so the run pauses before any command reaches the host.
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[ShellTools(requires_confirmation_tools=["run_shell_command"])],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_response = agent.run("List the files in the current directory")

    # run_shell_command is gated, so the run pauses for confirmation.
    if run_response.active_requirements:
        for requirement in run_response.active_requirements:
            if requirement.needs_confirmation:
                tool = requirement.tool_execution
                print(
                    f"Confirmation required for '{tool.tool_name}' with args: {tool.tool_args}"
                )
                answer = input("Approve? [y/N]: ").strip().lower()
                if answer == "y":
                    requirement.confirm()
                else:
                    requirement.reject()

        run_response = agent.continue_run(
            run_response, requirements=run_response.requirements
        )

    print(run_response.content)
