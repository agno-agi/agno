"""
Dual HITL: Step Confirmation + Executor Tool Confirmation (Streaming)
======================================================================

Two confirmation gates in one step:
  Pause 1 (step-level): Step has requires_confirmation=True -> user confirms before step runs
  Pause 2 (executor-level): Agent's tool has requires_confirmation=True -> user confirms tool call

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/dual_level_hitl/01_step_confirmation_and_tool_confirmation.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.run.workflow import (
    StepExecutorPausedEvent,
    StepPausedEvent,
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
def send_alert(city: str, message: str) -> str:
    """Send a weather alert for a city.

    Args:
        city: The city to send the alert for.
        message: The alert message.
    """
    return f"Alert sent for {city}: {message}"


alert_agent = Agent(
    name="AlertAgent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[send_alert],
    instructions="You send weather alerts. Always use the send_alert tool.",
    db=db,
    telemetry=False,
)


def log_result(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "nothing"
    return StepOutput(content=f"Logged: {prev}")


workflow = Workflow(
    name="DualConfirmation",
    db=db,
    steps=[
        Step(
            name="send_alert",
            agent=alert_agent,
            requires_confirmation=True,
            confirmation_message="This will send a weather alert. Proceed?",
        ),
        Step(name="log", executor=log_result),
    ],
    telemetry=False,
)


def resolve_step_pause(run_output):
    """Resolve step-level confirmation requirements."""
    for req in (run_output.step_requirements or [])[-1:]:
        if req.requires_confirmation and not req.requires_executor_input:
            console.print(f"  [dim]Message:[/] {req.confirmation_message}")
            answer = (
                Prompt.ask("  Confirm?", choices=["y", "n"], default="y")
                .strip()
                .lower()
            )
            if answer == "y":
                req.confirm()
            else:
                req.reject()


def resolve_executor_pause(run_output):
    """Resolve executor-level tool confirmation requirements."""
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
                Prompt.ask("  Approve tool call?", choices=["y", "n"], default="y")
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
    console.print("[bold]Dual HITL: Step Confirmation + Tool Confirmation[/]\n")

    pause_count = 0
    for event in workflow.run(
        "Send a weather alert for Tokyo about heavy rain", stream=True
    ):
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
            resolve_step_pause(run_output)

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
