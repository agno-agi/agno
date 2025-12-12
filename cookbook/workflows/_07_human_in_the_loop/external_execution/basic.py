import subprocess

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import tool
from agno.utils import pprint
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


@tool(external_execution=True)
def execute_shell_command(command: str) -> str:
    """Execute a shell command.
    Args:
        command (str): The shell command to execute
    Returns:
        str: The output of the shell command
    """
    if command.startswith("ls") or command.startswith("cat"):
        return subprocess.check_output(command, shell=True).decode("utf-8")
    else:
        raise Exception(f"Unsupported command: {command}")


# Step 1: List files agent (with external execution)
list_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    description="An agent that can list files in directories.",
    db=SqliteDb(db_file="tmp/external_execution_list.db"),
    tools=[execute_shell_command],
)
list_step = Step(name="List Files Step", agent=list_agent)


# Step 2: Analysis agent (no external execution - just processes results)
analysis_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    description="An agent that analyzes file information and provides insights.",
    instructions="Analyze the file listing and provide a summary of findings.",
    db=SqliteDb(db_file="tmp/external_execution_analysis.db"),
)
analysis_step = Step(name="Analysis Step", agent=analysis_agent)

# Define our Workflow
workflow = Workflow(
    name="File Analysis Workflow",
    description="A workflow that lists files and analyzes them",
    steps=[list_step, analysis_step],
)

run_output = workflow.run(
    input="List all Python files in the current directory, then analyze and summarize what types of files are present."
)

while run_output.is_paused:
    for requirement in run_output.active_requirements:
        if requirement.needs_external_execution:
            print(
                f"Executing {requirement.tool_execution.tool_name} with args {requirement.tool_execution.tool_args} externally"
            )
            result = execute_shell_command.entrypoint(
                **requirement.tool_execution.tool_args
            )
            requirement.set_external_execution_result(result)

    run_output = workflow.continue_run(
        run_id=run_output.run_id,
        requirements=run_output.requirements,
    )

pprint.pprint_run_response(run_output)
