"""
Multi-Round User Input
=============================

Demonstrates chained HITL where a member pauses multiple times for user input.
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

db = SqliteDb(session_table="team_multi_round_sessions", db_file="tmp/team_hitl.db")


@tool(requires_user_input=True, user_input_fields=["name"])
def collect_name(name: str = "") -> str:
    """Collect the user's name."""
    return f"User's name is: {name}"


@tool(requires_user_input=True, user_input_fields=["cuisine", "budget"])
def collect_preferences(cuisine: str = "", budget: str = "") -> str:
    """Collect user's dining preferences."""
    return f"User prefers {cuisine} cuisine with a {budget} budget."


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
survey_agent = Agent(
    name="SurveyAgent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[collect_name, collect_preferences],
    instructions=[
        "You help users find restaurant recommendations.",
        "You MUST collect information in this order:",
        "1. First, call collect_name to get the user's name",
        "2. Then, call collect_preferences to get their cuisine and budget preferences",
        "3. Finally, provide a personalized recommendation using both pieces of info",
    ],
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="RestaurantTeam",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[survey_agent],
    instructions="Delegate all restaurant requests to the SurveyAgent immediately.",
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "team_multi_round_session"
    run_response = team.run(
        "Help me find a restaurant for dinner tonight",
        session_id=session_id,
    )

    # Loop handles multiple pause/resume cycles (chained HITL)
    while run_response.is_paused:
        console.print("[bold yellow]Team is paused - user input needed[/]")

        for requirement in run_response.active_requirements:
            if requirement.needs_user_input:
                console.print(
                    f"Member [bold cyan]{requirement.member_agent_name}[/] needs input for "
                    f"[bold blue]{requirement.tool_execution.tool_name}[/]"
                )

                values = {}
                for field in requirement.user_input_schema or []:
                    values[field.name] = Prompt.ask(
                        f"  {field.name}", default=field.value or ""
                    )
                requirement.provide_user_input(values)

        run_response = team.continue_run(run_response)

    pprint.pprint_run_response(run_response)
