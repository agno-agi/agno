"""Team HITL Streaming: Member agent tool with external execution.

This example demonstrates how a team pauses when a member agent's tool
requires external execution in streaming mode. The tool result is provided
by the caller rather than being executed by the agent.

Note: When streaming with member agents, use isinstance() with TeamRunPausedEvent
to distinguish the team's pause from member agent pauses.
"""

import shlex
import subprocess

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.team.team import Team
from agno.tools import tool
from agno.utils import pprint

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/team_hitl_stream.db")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@tool(external_execution=True)
def run_shell_command(command: str) -> str:
    """Execute a shell command on the server.

    Args:
        command (str): The shell command to execute
    """
    return subprocess.check_output(shlex.split(command)).decode("utf-8")


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
ops_agent = Agent(
    name="Ops Agent",
    role="Handles server operations",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[run_shell_command],
    db=db,
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="SRE Team",
    members=[ops_agent],
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for run_event in team.run("List the files in the current directory", stream=True):
        # Use isinstance to check for team's pause event (not the member agent's)
        if isinstance(run_event, TeamRunPausedEvent):
            print("Team paused - requires external execution")
            for req in run_event.active_requirements:
                if req.needs_external_execution:
                    print(f"  Tool: {req.tool_execution.tool_name}")
                    print(f"  Args: {req.tool_execution.tool_args}")

                    # Execute the tool externally
                    result = run_shell_command.entrypoint(
                        **req.tool_execution.tool_args
                    )
                    req.set_external_execution_result(result)

            response = team.continue_run(
                run_id=run_event.run_id,
                session_id=run_event.session_id,
                requirements=run_event.requirements,
                stream=True,
            )
            pprint.pprint_run_response(response)
