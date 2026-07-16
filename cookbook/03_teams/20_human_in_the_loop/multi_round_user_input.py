"""
Multi-Round User Input (Chained HITL)
=====================================

Demonstrates a member agent that pauses MULTIPLE times for user input
during a single team execution. This is the scenario from issue #8925.

The member agent has TWO tools that require user input:
1. collect_name() - asks for user's name
2. collect_preferences() - asks for user's preferences

The agent calls both tools in sequence, causing TWO pause/resume cycles.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools import tool
from agno.utils import pprint
from rich.console import Console
from rich.prompt import Prompt

console = Console()

db = SqliteDb(
    session_table="multi_round_hitl_sessions",
    db_file="tmp/multi_round_hitl.db",
)


@tool(requires_user_input=True, user_input_fields=["name"])
def collect_name(name: str = "") -> str:
    """Collect the user's name. Call this first before collecting preferences."""
    return f"User's name is: {name}"


@tool(requires_user_input=True, user_input_fields=["cuisine", "budget"])
def collect_preferences(cuisine: str = "", budget: str = "") -> str:
    """Collect user's dining preferences. Call this after getting their name."""
    return f"User prefers {cuisine} cuisine with a {budget} budget."


survey_agent = Agent(
    name="SurveyAgent",
    model=OpenAIResponses(id="gpt-5-mini"),
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

team = Team(
    name="RestaurantTeam",
    model=OpenAIResponses(id="gpt-5-mini"),
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


if __name__ == "__main__":
    session_id = "multi_round_hitl_session"

    console.print("\n[bold green]Multi-Round HITL Demo[/]")
    console.print("This demo shows a member agent pausing TWICE for user input.\n")

    # Initial run
    console.print("[cyan]Starting team.run()...[/]")
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

        console.print(f"\n[cyan]Calling team.continue_run() (round {round_num})...[/]")
        run_response = team.continue_run(run_response, session_id=session_id)

        round_num += 1
        if round_num > 5:
            console.print("[bold red]Too many rounds, breaking[/]")
            break

    console.print("\n[bold green]===== Final Result =====[/]")
    pprint.pprint_run_response(run_response)
