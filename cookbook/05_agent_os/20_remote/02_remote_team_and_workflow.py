"""
Run a Team and Workflow on another AgentOS
==========================================

RemoteTeam and RemoteWorkflow use the native AgentOS protocol while returning
typed Agno Team and Workflow outputs to the caller.

Prerequisites: start `servers/agentos_server.py` and set OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/20_remote/02_remote_team_and_workflow.py
Try: ask the Team for a conceptual answer and the Workflow for arithmetic
"""

import asyncio

from agno.team import RemoteTeam
from agno.workflow import RemoteWorkflow

BASE_URL = "http://127.0.0.1:7780"

# ---------------------------------------------------------------------------
# Create Remote Team and Workflow
# ---------------------------------------------------------------------------

remote_team = RemoteTeam(
    base_url=BASE_URL,
    team_id="research-team",
)

remote_workflow = RemoteWorkflow(
    base_url=BASE_URL,
    workflow_id="qa-workflow",
)

# ---------------------------------------------------------------------------
# Run Remote Team and Workflow
# ---------------------------------------------------------------------------


async def run_remote_components() -> None:
    """Run both native AgentOS component types."""
    team_response = await remote_team.arun(
        "In two bullets, explain how an Agent differs from a Workflow.",
        session_id="remote-team-session",
    )
    print(f"Team run: {team_response.run_id}")
    print(team_response.content)

    workflow_response = await remote_workflow.arun(
        "Use the calculator to divide 144 by 12.",
        session_id="remote-workflow-session",
    )
    print(f"\nWorkflow run: {workflow_response.run_id}")
    print(workflow_response.content)


if __name__ == "__main__":
    asyncio.run(run_remote_components())
