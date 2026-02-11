"""Team HITL Streaming: Tool on the team itself requiring confirmation.

This example demonstrates HITL for tools provided directly to the Team
(not to member agents) in streaming mode. When the team leader decides
to use a tool that requires confirmation, the entire team run pauses
until the human confirms.

Note: For team-level tools (not member agent tools), you can use either
isinstance(event, TeamRunPausedEvent) or event.is_paused since there's
no member agent pause to confuse it with.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.team.team import Team
from agno.tools import tool
from agno.utils import pprint

db = SqliteDb(db_file="tmp/team_hitl_stream.db")


@tool(requires_confirmation=True)
def approve_deployment(environment: str, service: str) -> str:
    """Approve and execute a deployment to an environment.

    Args:
        environment (str): Target environment (staging, production)
        service (str): Service to deploy
    """
    return f"Deployment of {service} to {environment} approved and executed"


research_agent = Agent(
    name="Research Agent",
    role="Researches deployment readiness",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
)

team = Team(
    name="Release Team",
    members=[research_agent],
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[approve_deployment],
    db=db,
)


for run_event in team.run("Check if the auth service is ready and deploy it to staging", stream=True):
    # Use isinstance to check for team's pause event
    if isinstance(run_event, TeamRunPausedEvent):
        print("Team paused - requires confirmation for team-level tool")
        for req in run_event.active_requirements:
            if req.needs_confirmation:
                print(f"  Tool: {req.tool_execution.tool_name}")
                print(f"  Args: {req.tool_execution.tool_args}")
                req.confirm()

        response = team.continue_run(
            run_id=run_event.run_id,
            session_id=run_event.session_id,
            requirements=run_event.requirements,
            stream=True,
        )
        pprint.pprint_run_response(response)
