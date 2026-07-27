"""
StepExecutorContinuedEvent Demo (Streaming)
=============================================

Demonstrates the StepExecutorContinuedEvent that is emitted when a paused
executor (agent/team) resumes after executor-level HITL is resolved.

Event flow:
  StepExecutorPausedEvent    -> agent's tool call paused, waiting for confirmation
  StepExecutorContinuedEvent -> user confirmed, executor is now resuming
  WorkflowCompletedEvent     -> workflow finished

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/executor_hitl/09_executor_continued_event.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.run.workflow import (
    StepExecutorContinuedEvent,
    StepExecutorPausedEvent,
    WorkflowCompletedEvent,
)
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
    instructions="You provide weather information. Always use the get_the_weather tool.",
    db=db,
    telemetry=False,
)


def save_result(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "nothing"
    return StepOutput(content=f"Saved: {prev}")


workflow = Workflow(
    name="ExecutorContinuedEventDemo",
    db=db,
    steps=[
        Step(name="get_weather", agent=weather_agent),
        Step(name="save", executor=save_result),
    ],
    telemetry=False,
)


def process_events(event_stream):
    """Process and display events, highlighting continued events."""
    for event in event_stream:
        if isinstance(event, StepExecutorPausedEvent):
            console.print(
                f"  [yellow]StepExecutorPausedEvent: {event.executor_name} "
                f"({event.executor_type})[/]"
            )
        elif isinstance(event, StepExecutorContinuedEvent):
            console.print(
                f"  [cyan]StepExecutorContinuedEvent: {event.executor_name} "
                f"({event.executor_type})[/]"
            )
        elif isinstance(event, WorkflowCompletedEvent):
            console.print("  [bold green]WorkflowCompletedEvent[/]")
        elif hasattr(event, "content") and event.content:
            print(f"  {event.content}", end="", flush=True)


if __name__ == "__main__":
    console.print("[bold]StepExecutorContinuedEvent Demo[/]\n")
    console.print(
        "Watch for StepExecutorContinuedEvent after approving the tool call.\n"
    )

    # Initial run — agent will pause when it tries to call get_the_weather
    console.print("[bold]--- Initial run ---[/]")
    process_events(workflow.run("What is the weather in Tokyo?", stream=True))

    session = workflow.get_session()
    run_output = session.runs[-1] if session and session.runs else None

    if run_output and run_output.is_paused:
        for req in run_output.step_requirements or []:
            if req.requires_executor_input:
                console.print(f"\n[yellow]Executor paused: {req.executor_name}[/]")

                for executor_req in req.executor_requirements or []:
                    tool_exec = (
                        executor_req.get("tool_execution", {})
                        if isinstance(executor_req, dict)
                        else getattr(executor_req, "tool_execution", None)
                    )
                    if tool_exec:
                        t_name = (
                            tool_exec.get("tool_name", "?")
                            if isinstance(tool_exec, dict)
                            else getattr(tool_exec, "tool_name", "?")
                        )
                        console.print(f"  Tool: [bold blue]{t_name}[/]")

                answer = (
                    Prompt.ask("Approve?", choices=["y", "n"], default="y")
                    .strip()
                    .lower()
                )
                for executor_req in req.executor_requirements or []:
                    if isinstance(executor_req, dict):
                        executor_req["confirmation"] = answer == "y"
                        if (
                            "tool_execution" in executor_req
                            and executor_req["tool_execution"]
                        ):
                            executor_req["tool_execution"]["confirmed"] = answer == "y"
                    else:
                        executor_req.confirm() if answer == "y" else executor_req.reject(
                            note="Declined"
                        )

        # Continue — StepExecutorContinuedEvent should appear here
        console.print("\n[bold]--- Continue run ---[/]")
        process_events(workflow.continue_run(run_output, stream=True))

        session = workflow.get_session()
        run_output = session.runs[-1] if session and session.runs else None

    console.print(
        f"\n[bold green]Final: {run_output.content if run_output else 'N/A'}[/]"
    )
