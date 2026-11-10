"""
External Tool Execution
=============================

Demonstrates resolving external tool execution requirements in team flows.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools import tool
from agno.utils import pprint
from rich.console import Console
from rich.prompt import Prompt

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
console = Console()

db = SqliteDb(session_table="team_ext_exec_sessions", db_file="tmp/team_hitl.db")


@tool(external_execution=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to someone. Executed externally."""
    return ""


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
email_agent = Agent(
    name="EmailAgent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[send_email],
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="CommunicationTeam",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[email_agent],
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "team_email_session"
    run_response = team.run(
        "Send an email to john@example.com with subject 'Meeting Tomorrow' and body 'Let's meet at 3pm.'",
        session_id=session_id,
    )

    if run_response.is_paused:
        console.print("[bold yellow]Team is paused - external execution needed[/]")

        for requirement in run_response.active_requirements:
            if requirement.needs_external_execution:
                tool_args = requirement.tool_execution.tool_args
                console.print(
                    f"Member [bold cyan]{requirement.member_agent_name}[/] needs external execution of "
                    f"[bold blue]{requirement.tool_execution.tool_name}[/]"
                )
                console.print(f"  To: {tool_args.get('to')}")
                console.print(f"  Subject: {tool_args.get('subject')}")
                console.print(f"  Body: {tool_args.get('body')}")

                result = Prompt.ask(
                    "Enter the result of the email send",
                    default="Email sent successfully",
                )
                requirement.set_external_execution_result(result)

        run_response = team.continue_run(run_response)

    pprint.pprint_run_response(run_response)
