"""Human-in-the-Loop for Teams: User Input Required

This example shows how to collect user input when a member agent's tool
needs additional information before it can execute.

The tool defines which fields need user input via user_input_fields.
When the tool is called, the agent pauses and presents the input schema
to the user for completion.

Run `pip install openai agno` to install dependencies.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools import tool
from agno.utils import pprint
from rich.console import Console
from rich.prompt import Prompt

console = Console()

db = SqliteDb(session_table="team_user_input_sessions", db_file="tmp/team_hitl.db")


@tool(requires_user_input=True, user_input_fields=["destination", "budget"])
def plan_trip(destination: str = "", budget: str = "") -> str:
    """Plan a trip based on user preferences."""
    return f"Trip planned to {destination} with a budget of {budget}. Includes flights, hotel, and activities."


# Create the member agent
travel_agent = Agent(
    name="TravelAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[plan_trip],
    db=db,
    telemetry=False,
)

# Create the team
team = Team(
    name="TravelTeam",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[travel_agent],
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

if __name__ == "__main__":
    # Run the team
    session_id = "team_travel_session"
    run_response = team.run("Help me plan a vacation", session_id=session_id)

    if run_response.is_paused:
        console.print("[bold yellow]Team is paused - user input needed[/]")

        for requirement in run_response.active_requirements:
            if requirement.needs_user_input:
                console.print(
                    f"Member [bold cyan]{requirement.member_agent_name}[/] needs input for "
                    f"[bold blue]{requirement.tool_execution.tool_name}[/]"
                )

                # Collect user input values
                values = {}
                for field in requirement.user_input_schema or []:
                    values[field.name] = Prompt.ask(
                        f"  {field.name}", default=field.value or ""
                    )
                requirement.provide_user_input(values)

        # Continue the team run with the user input
        run_response = team.continue_run(run_response)

    pprint.pprint_run_response(run_response)
