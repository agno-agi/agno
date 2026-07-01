"""
Dual HITL: Step User Input + Executor Tool Confirmation (Streaming)
====================================================================

Two different HITL types in one step:
  Pause 1 (step-level): Step has requires_user_input=True -> collects city name from user
  Pause 2 (executor-level): Agent's tool has requires_confirmation=True -> user confirms tool call

The user input is injected into step_input.additional_data["user_input"] and the agent
receives it as context.

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/dual_level_hitl/02_step_user_input_and_tool_confirmation.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.run.workflow import (
    StepExecutorPausedEvent,
    StepPausedEvent,
    WorkflowCompletedEvent,
)
from agno.tools import tool
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


@tool(requires_confirmation=True)
def book_flight(origin: str, destination: str) -> str:
    """Book a flight between two cities.

    Args:
        origin: Departure city.
        destination: Arrival city.
    """
    return f"Flight booked: {origin} -> {destination}"


travel_agent = Agent(
    name="TravelAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[book_flight],
    instructions=(
        "You are a travel agent. Use the book_flight tool to book flights. "
        "Check the user_input in the context for the destination city."
    ),
    db=db,
    telemetry=False,
)


workflow = Workflow(
    name="UserInputAndToolConfirm",
    db=db,
    steps=[
        Step(
            name="book_travel",
            agent=travel_agent,
            requires_user_input=True,
            user_input_message="Which city do you want to fly to?",
            user_input_schema=[
                {
                    "name": "destination",
                    "field_type": "text",
                    "description": "Destination city",
                    "required": True,
                },
            ],
        ),
    ],
    telemetry=False,
)


def resolve_user_input_pause(run_output):
    """Collect user input for step-level HITL."""
    for req in (run_output.step_requirements or [])[-1:]:
        if req.requires_user_input and not req.requires_executor_input:
            console.print(f"  [dim]{req.user_input_message}[/]")
            if req.user_input_schema:
                user_input = {}
                for field in req.user_input_schema:
                    val = Prompt.ask(f"  {field.name}: {field.description}")
                    field.value = (
                        val  # Set value on the schema field so is_resolved works
                    )
                    user_input[field.name] = val
                req.user_input = user_input
            else:
                req.user_input = Prompt.ask("  Your input")
            req.confirmed = True


def resolve_executor_pause(run_output):
    """Resolve executor-level tool confirmation."""
    for req in (run_output.step_requirements or [])[-1:]:
        if req.requires_executor_input:
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
                    t_args = (
                        tool_exec.get("tool_args", {})
                        if isinstance(tool_exec, dict)
                        else getattr(tool_exec, "tool_args", {})
                    )
                    console.print(f"  Tool: [bold blue]{t_name}({t_args})[/]")

            answer = (
                Prompt.ask("  Approve?", choices=["y", "n"], default="y")
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


if __name__ == "__main__":
    console.print("[bold]Dual HITL: Step User Input + Tool Confirmation[/]\n")

    pause_count = 0
    for event in workflow.run("Book a flight from San Francisco", stream=True):
        if isinstance(event, StepPausedEvent):
            console.print(f"\n[yellow]Step paused: {event.step_name}[/]")
        elif isinstance(event, StepExecutorPausedEvent):
            console.print(f"\n[yellow]Executor paused: {event.executor_name}[/]")
        elif isinstance(event, WorkflowCompletedEvent):
            console.print("\n[green]Workflow completed![/]")
        elif hasattr(event, "content") and event.content:
            print(event.content, end="", flush=True)

    session = workflow.get_session()
    run_output = session.runs[-1] if session and session.runs else None

    while run_output and run_output.is_paused:
        pause_count += 1
        # Only check the LAST (active) requirement — earlier ones are resolved history
        _active = (run_output.step_requirements or [])[-1:]
        has_executor = any(r.requires_executor_input for r in _active)
        console.print(
            f"\n[bold magenta]--- Pause #{pause_count} ({'executor' if has_executor else 'step'}-level) ---[/]"
        )

        if has_executor:
            resolve_executor_pause(run_output)
        else:
            resolve_user_input_pause(run_output)

        for event in workflow.continue_run(run_output, stream=True):
            if isinstance(event, StepPausedEvent):
                console.print(f"\n[yellow]Step paused: {event.step_name}[/]")
            elif isinstance(event, StepExecutorPausedEvent):
                console.print(f"\n[yellow]Executor paused: {event.executor_name}[/]")
            elif isinstance(event, WorkflowCompletedEvent):
                console.print("\n[green]Workflow completed![/]")
            elif hasattr(event, "content") and event.content:
                print(event.content, end="", flush=True)

        session = workflow.get_session()
        run_output = session.runs[-1] if session and session.runs else None

    console.print(
        f"\n[bold green]Done after {pause_count} pause(s). Output: {run_output.content if run_output else 'N/A'}[/]"
    )
