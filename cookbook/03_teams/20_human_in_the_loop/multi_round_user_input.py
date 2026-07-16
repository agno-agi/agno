"""
Multi-Round User Input (Chained HITL)
=====================================

Demonstrates a member agent that pauses multiple times for user input
during a single team execution. Regression test for issue #8925.
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

db = SqliteDb(
    session_table="multi_round_hitl_sessions",
    db_file="tmp/multi_round_hitl.db",
)


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
    instructions=[
        "You are a coordinator. You NEVER answer directly.",
        "ALWAYS delegate to SurveyAgent for any restaurant or dining request.",
        "Do not provide your own suggestions - only delegate.",
    ],
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "multi_round_hitl_session"

    console.print("\n[bold green]Multi-Round HITL Demo[/]")
    console.print("This demo shows a member agent pausing TWICE for user input.\n")

    run_response = team.run(
        "Help me find a restaurant for dinner tonight",
        session_id=session_id,
    )

    round_num = 1
    while run_response.is_paused:
        console.print(f"\n[bold yellow]===== HITL Round {round_num} =====[/]")

        for requirement in run_response.active_requirements:
            if requirement.needs_user_input:
                tool_name = requirement.tool_execution.tool_name
                console.print(
                    f"Member [bold cyan]{requirement.member_agent_name}[/] "
                    f"needs input for [bold blue]{tool_name}[/]"
                )

                values = {}
                for field in requirement.user_input_schema or []:
                    values[field.name] = Prompt.ask(
                        f"  {field.name}",
                        default=field.value or "",
                    )
                requirement.provide_user_input(values)

        run_response = team.continue_run(run_response, session_id=session_id)

        round_num += 1
        if round_num > 5:
            console.print("[bold red]Too many rounds, breaking[/]")
            break

    console.print("\n[bold green]===== Final Result =====[/]")
    pprint.pprint_run_response(run_response)
