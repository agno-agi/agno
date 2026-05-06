"""
Team Member HITL - Confirm Before Member Takes Action
======================================================
This example shows how a Team member agent can require user confirmation
before executing sensitive tools. The approval flow works across DB
persistence - critical for API/Slack integrations.

Key concepts:
- Member agent with @tool(requires_confirmation=True)
- Team propagates member's pause to TeamRunPausedEvent
- DB persistence: run can be continued after reload
- session.get_run() recovers member runs from TeamSession

Flow:
1. User asks Team to deploy
2. Team delegates to DeployAgent
3. DeployAgent's deploy_code tool requires confirmation
4. Team pauses with the member's requirement
5. User approves/rejects
6. Team continues the member's run

Run: .venvs/demo/bin/python cookbook/03_teams/18_human_in_the_loop/member_confirmation.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools import tool
from agno.utils import pprint
from rich.console import Console
from rich.prompt import Prompt

# ---------------------------------------------------------------------------
# Database Configuration (PostgreSQL for persistence)
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Member Tools - Requires Confirmation
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def deploy_code(environment: str, version: str = "latest") -> str:
    """
    Deploy code to the specified environment.
    This action requires user confirmation before executing.

    Args:
        environment: Target environment (staging, production)
        version: Version to deploy (default: latest)

    Returns:
        Deployment status message
    """
    return f"Successfully deployed version {version} to {environment}"


@tool(requires_confirmation=True)
def rollback_deployment(environment: str) -> str:
    """
    Rollback to the previous deployment.
    This action requires user confirmation before executing.

    Args:
        environment: Target environment to rollback

    Returns:
        Rollback status message
    """
    return f"Successfully rolled back {environment} to previous version"


# ---------------------------------------------------------------------------
# Member Agent: DeployAgent
# ---------------------------------------------------------------------------
deploy_agent = Agent(
    name="DeployAgent",
    id="deploy-agent",
    model=OpenAIResponses(id="gpt-4.1-mini"),
    tools=[deploy_code, rollback_deployment],
    instructions=[
        "You are a deployment agent. ALWAYS use your tools to take action.",
        "When asked to deploy, IMMEDIATELY call deploy_code with the target environment.",
        "When asked to rollback, IMMEDIATELY call rollback_deployment.",
        "Do NOT ask for confirmation in your response - the tools handle that.",
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Team: DevOps Team
# ---------------------------------------------------------------------------
devops_team = Team(
    name="DevOpsTeam",
    id="devops-team",
    mode="coordinate",
    model=OpenAIResponses(id="gpt-4.1-mini"),
    members=[deploy_agent],
    instructions=[
        "You are a DevOps coordinator. ALWAYS delegate to your team members.",
        "For ANY deployment request, IMMEDIATELY delegate to DeployAgent.",
        "Do NOT try to handle deployments yourself - use your team member.",
    ],
    db=db,
    # NOTE: store_member_responses=False (default)
    # The fix in this branch allows recovery via session.get_run()
)

# ---------------------------------------------------------------------------
# Run the Team with HITL
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console = Console()
    session_id = "devops-session-001"

    console.print("\n[bold cyan]Team Member HITL Demo[/bold cyan]")
    console.print("=" * 50)

    # Step 1: Run the team - should pause for confirmation
    console.print("\n[bold]Step 1:[/bold] Running team with deployment request...")

    run_response = devops_team.run(
        "Deploy the latest version to production",
        session_id=session_id,
    )

    # Print initial response
    if run_response.content:
        pprint.pprint_run_response(run_response)

    # Step 2: Check for confirmation requirements
    if run_response.is_paused and run_response.active_requirements:
        console.print("\n[bold yellow]Team paused - member needs confirmation[/bold yellow]")

        for req in run_response.active_requirements:
            console.print(f"\n[bold]Requirement:[/bold]")
            console.print(f"  Tool: [blue]{req.tool_execution.tool_name}[/blue]")
            console.print(f"  Args: {req.tool_execution.tool_args}")
            console.print(f"  Member: {req.member_agent_id}")
            console.print(f"  Member Run ID: {req.member_run_id}")

            # Simulate API flow: clear runtime pointer
            # In real API flow, this is lost during JSON serialization
            req._member_run_response = None

            choice = Prompt.ask(
                "\nApprove this action?",
                choices=["y", "n"],
                default="y",
            ).strip().lower()

            if choice == "n":
                req.reject(reason="User rejected deployment")
                console.print("[red]Rejected[/red]")
            else:
                req.confirm()
                console.print("[green]Approved[/green]")

        # Step 3: Simulate DB reload (API/Slack flow)
        # In real flow, run_response would be loaded from DB via aget_run_output()
        # Here we just ensure _member_run_response is None to test session.get_run()
        console.print("\n[bold]Step 3:[/bold] Continuing run (simulating API flow)...")
        console.print("  _member_run_response = None (simulating serialization loss)")
        console.print("  member_responses = [] (store_member_responses=False)")

        # Clear member_responses to ensure we test the session.get_run() path
        run_response.member_responses = []

        # Step 4: Continue the run
        continue_response = devops_team.continue_run(
            run_response=run_response,
            session_id=session_id,
        )

        console.print("\n[bold]Step 4:[/bold] Final result:")
        pprint.pprint_run_response(continue_response)

        if not continue_response.is_paused:
            console.print("\n[bold green]SUCCESS![/bold green] Team member HITL completed.")
        else:
            console.print("\n[bold yellow]Still paused[/bold yellow] - may have chained HITL.")

    else:
        console.print("\n[bold red]Unexpected:[/bold red] Run did not pause for confirmation.")
        console.print(f"is_paused: {run_response.is_paused}")
        console.print(f"requirements: {run_response.requirements}")

# ---------------------------------------------------------------------------
# Expected Output
# ---------------------------------------------------------------------------
"""
Team Member HITL Demo
==================================================

Step 1: Running team with deployment request...
[Agent response about deploying...]

Team paused - member needs confirmation

Requirement:
  Tool: deploy_code
  Args: {'environment': 'production', 'version': 'latest'}
  Member: deploy-agent
  Member Run ID: abc123...

Approve this action? [y/n] (y): y
Approved

Step 3: Continuing run (simulating API flow)...
  _member_run_response = None (simulating serialization loss)
  member_responses = [] (store_member_responses=False)

Step 4: Final result:
[Final response with deployment confirmation...]

SUCCESS! Team member HITL completed.
"""
