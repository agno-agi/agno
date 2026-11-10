"""
Confirmation Required
=============================

Demonstrates team-level pause/continue flow for confirmation-required member tools.
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

db = SqliteDb(session_table="team_hitl_sessions", db_file="tmp/team_hitl.db")


@tool(requires_confirmation=True)
def get_the_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"It is currently 70 degrees and cloudy in {city}"


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
weather_agent = Agent(
    name="WeatherAgent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_the_weather],
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="WeatherTeam",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[weather_agent],
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
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
                    Prompt.ask(
                        "Do you want to approve?", choices=["y", "n"], default="y"
                    )
                    .strip()
                    .lower()
                )

                if message == "n":
                    requirement.reject(note="User declined")
                else:
                    requirement.confirm()

        run_response = team.continue_run(run_response)

    pprint.pprint_run_response(run_response)
