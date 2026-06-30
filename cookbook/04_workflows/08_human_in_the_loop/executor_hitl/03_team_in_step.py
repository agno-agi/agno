"""
Team-in-Step Executor HITL
============================

Demonstrates executor-level HITL when a Team is used inside a workflow Step.
The team's member agent has a tool with `requires_confirmation=True`.
The pause propagates: member agent -> team -> step -> workflow.

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/executor_hitl/03_team_in_step.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools import tool
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


@tool(requires_confirmation=True)
def get_the_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city to get weather for.
    """
    return f"It is currently 70 degrees and cloudy in {city}"


weather_agent = Agent(
    name="WeatherAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_the_weather],
    db=db,
    telemetry=False,
)

weather_team = Team(
    name="WeatherTeam",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[weather_agent],
    db=db,
    telemetry=False,
    instructions=[
        "You MUST delegate all weather-related tasks to the WeatherAgent.",
        "Do NOT try to answer weather questions yourself.",
    ],
)


def save_result(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "no previous content"
    return StepOutput(content=f"Result saved: {prev}")


workflow = Workflow(
    name="TeamWeatherWorkflow",
    db=db,
    steps=[
        Step(name="team_weather", team=weather_team),
        Step(name="save", executor=save_result),
    ],
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = workflow.run("What is the weather in Tokyo?")

    if response.is_paused and response.step_requirements:
        for step_req in response.step_requirements:
            if step_req.requires_executor_input:
                console.print(
                    f"[bold yellow]Workflow paused at step '{step_req.step_name}'[/]\n"
                    f"Executor: [bold cyan]{step_req.executor_name}[/] "
                    f"(type: {step_req.executor_type})"
                )

                for executor_req in step_req.executor_requirements or []:
                    tool_exec = (
                        executor_req.get("tool_execution", {})
                        if isinstance(executor_req, dict)
                        else getattr(executor_req, "tool_execution", None)
                    )
                    if tool_exec:
                        tool_name = (
                            tool_exec.get("tool_name", "?")
                            if isinstance(tool_exec, dict)
                            else getattr(tool_exec, "tool_name", "?")
                        )
                        tool_args = (
                            tool_exec.get("tool_args", {})
                            if isinstance(tool_exec, dict)
                            else getattr(tool_exec, "tool_args", {})
                        )
                        console.print(f"  Tool: [bold blue]{tool_name}({tool_args})[/]")

                answer = (
                    Prompt.ask("Approve?", choices=["y", "n"], default="y")
                    .strip()
                    .lower()
                )

                for executor_req in step_req.executor_requirements or []:
                    if isinstance(executor_req, dict):
                        executor_req["confirmation"] = answer == "y"
                        if (
                            "tool_execution" in executor_req
                            and executor_req["tool_execution"]
                        ):
                            executor_req["tool_execution"]["confirmed"] = answer == "y"
                    else:
                        if answer == "y":
                            executor_req.confirm()
                        else:
                            executor_req.reject(note="User declined")

        response = workflow.continue_run(response)

    console.print(f"\n[bold green]Final output:[/] {response.content}")
