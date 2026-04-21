"""
StepContinuedEvent Demo (Streaming)
=====================================

Demonstrates the StepContinuedEvent that is emitted when a paused step
resumes execution after step-level HITL is resolved.

Event flow:
  StepPausedEvent    -> workflow paused, waiting for confirmation
  StepContinuedEvent -> user confirmed, step is now executing
  StepCompletedEvent -> step finished

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/confirmation/04_step_continued_event.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.run.workflow import (
    StepCompletedEvent,
    StepContinuedEvent,
    StepPausedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
)
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

greeting_agent = Agent(
    name="GreetingAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You greet people warmly. Keep it to one sentence.",
    db=db,
    telemetry=False,
)


def save_result(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "nothing"
    return StepOutput(content=f"Saved: {prev}")


workflow = Workflow(
    name="ContinuedEventDemo",
    db=db,
    steps=[
        Step(
            name="greet",
            agent=greeting_agent,
            requires_confirmation=True,
            confirmation_message="About to generate a greeting. Proceed?",
        ),
        Step(name="save", executor=save_result),
    ],
    telemetry=False,
)


def process_events(event_stream):
    """Process and display events from the stream."""
    for event in event_stream:
        if isinstance(event, StepStartedEvent):
            console.print(f"  [dim]StepStartedEvent: {event.step_name}[/]")
        elif isinstance(event, StepPausedEvent):
            console.print(f"  [yellow]StepPausedEvent: {event.step_name}[/]")
        elif isinstance(event, StepContinuedEvent):
            console.print(f"  [cyan]StepContinuedEvent: {event.step_name}[/]")
        elif isinstance(event, StepCompletedEvent):
            console.print(f"  [green]StepCompletedEvent: {event.step_name}[/]")
        elif isinstance(event, WorkflowCompletedEvent):
            console.print("  [bold green]WorkflowCompletedEvent[/]")
        elif hasattr(event, "content") and event.content:
            print(f"  {event.content}", end="", flush=True)


if __name__ == "__main__":
    console.print("[bold]StepContinuedEvent Demo[/]\n")
    console.print("Watch for StepContinuedEvent after confirming the paused step.\n")

    # Initial run — will pause at the confirmation step
    console.print("[bold]--- Initial run ---[/]")
    process_events(workflow.run("Hello world", stream=True, stream_events=True))

    session = workflow.get_session()
    run_output = session.runs[-1] if session and session.runs else None

    if run_output and run_output.is_paused:
        for req in run_output.step_requirements or []:
            if req.requires_confirmation:
                console.print(
                    f"\n[yellow]Paused at '{req.step_name}': {req.confirmation_message}[/]"
                )
                answer = (
                    Prompt.ask("Confirm?", choices=["y", "n"], default="y")
                    .strip()
                    .lower()
                )
                if answer == "y":
                    req.confirm()
                else:
                    req.reject()

        # Continue — StepContinuedEvent should appear here
        console.print("\n[bold]--- Continue run ---[/]")
        process_events(
            workflow.continue_run(run_output, stream=True, stream_events=True)
        )

        session = workflow.get_session()
        run_output = session.runs[-1] if session and session.runs else None

    console.print(
        f"\n[bold green]Final: {run_output.content if run_output else 'N/A'}[/]"
    )
