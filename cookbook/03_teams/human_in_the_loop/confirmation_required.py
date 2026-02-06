"""Human-in-the-Loop for Teams: Member Tool Confirmation

This example shows how human-in-the-loop works when a team member agent has
a tool that requires user confirmation before execution.

When a member agent encounters a confirmation-required tool:
1. The member agent pauses
2. The pause propagates up to the team level
3. The team's run_response contains requirements with member context
4. The user resolves the requirements
5. team.continue_run() routes back to the member and completes

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

db = SqliteDb(session_table="team_hitl_sessions", db_file="tmp/team_hitl.db")


@tool(requires_confirmation=True)
def get_the_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"It is currently 70 degrees and cloudy in {city}"


# Create the member agent with a confirmation-required tool
weather_agent = Agent(
    name="WeatherAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_the_weather],
    db=db,
    telemetry=False,
)

# Create the team with the member
team = Team(
    name="WeatherTeam",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[weather_agent],
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

# Run the team - this will pause when the member needs confirmation
session_id = "team_weather_session"
run_response = team.run("What is the weather in Tokyo?", session_id=session_id)

if run_response.is_paused:
    console.print("[bold yellow]Team is paused - member needs confirmation[/]")

    for requirement in run_response.active_requirements:
        if requirement.needs_confirmation:
            console.print(
                f"Member [bold cyan]{requirement.member_agent_name}[/] wants to call "
                f"[bold blue]{requirement.tool_execution.tool_name}"
                f"({requirement.tool_execution.tool_args})[/]"
            )

            message = (
                Prompt.ask("Do you want to approve?", choices=["y", "n"], default="y")
                .strip()
                .lower()
            )

            if message == "n":
                requirement.reject(note="User declined")
            else:
                requirement.confirm()

    # Continue the team run
    run_response = team.continue_run(run_response)

pprint.pprint_run_response(run_response)
