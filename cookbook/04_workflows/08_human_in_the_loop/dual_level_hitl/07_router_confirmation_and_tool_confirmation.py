"""
Dual HITL: Router Confirmation + Executor Tool Confirmation (Streaming)
========================================================================

Router as a pre-execution gate (not route selection):
  Pause 1 (router-level): Router has requires_confirmation=True -> user confirms
          before the router executes its selector and chosen branch
  Pause 2 (executor-level): The agent on the chosen route has a tool with
          requires_confirmation=True -> user confirms the tool call

Unlike 04 (Router user selection), here the Router's selector picks the route
automatically and the user just confirms/rejects the overall execution.

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/dual_level_hitl/07_router_confirmation_and_tool_confirmation.py
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
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


@tool(requires_confirmation=True)
def restart_service(service: str) -> str:
    """Restart a production service.

    Args:
        service: The service name to restart.
    """
    return f"Service '{service}' restarted successfully"


@tool(requires_confirmation=True)
def scale_service(service: str, replicas: int) -> str:
    """Scale a service to a given number of replicas.

    Args:
        service: The service name.
        replicas: Target replica count.
    """
    return f"Service '{service}' scaled to {replicas} replicas"


restart_agent = Agent(
    name="RestartAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[restart_service],
    instructions="You restart services. Always use restart_service. Call it exactly once.",
    db=db,
    telemetry=False,
)

scale_agent = Agent(
    name="ScaleAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[scale_service],
    instructions="You scale services. Always use scale_service. Call it exactly once.",
    db=db,
    telemetry=False,
)


def select_action(step_input: StepInput) -> list:
    """Selector: picks 'restart' for any input containing 'restart', else 'scale'."""
    text = str(step_input.input or "").lower()
    if "restart" in text:
        return [Step(name="restart", agent=restart_agent)]
    return [Step(name="scale", agent=scale_agent)]


workflow = Workflow(
    name="RouterConfirmAndToolConfirm",
    db=db,
    steps=[
        Router(
            name="ops_router",
            choices=[
                Step(name="restart", agent=restart_agent),
                Step(name="scale", agent=scale_agent),
            ],
            selector=select_action,
            requires_confirmation=True,
            confirmation_message="An ops action will be executed. Proceed?",
        ),
    ],
    telemetry=False,
)


def resolve_step_pause(run_output):
    for req in (run_output.step_requirements or [])[-1:]:
        if req.requires_confirmation and not req.requires_executor_input:
            console.print(f"  [dim]{req.confirmation_message}[/]")
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
    for req in (run_output.step_requirements or [])[-1:]:
        if req.requires_executor_input:
            console.print(f"  Executor: [cyan]{req.executor_name}[/]")
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
    console.print("[bold]Dual HITL: Router Confirmation + Tool Confirmation[/]\n")

    pause_count = 0
    for event in workflow.run("Restart the auth-service", stream=True):
        if isinstance(event, StepPausedEvent):
            console.print(f"\n[yellow]Paused: {event.step_name}[/]")
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
        label = "executor" if has_executor else "router-confirmation"
        console.print(f"\n[bold magenta]--- Pause #{pause_count} ({label}) ---[/]")

        if has_executor:
            resolve_executor_pause(run_output)
        else:
            resolve_step_pause(run_output)

        for event in workflow.continue_run(run_output, stream=True):
            if isinstance(event, StepPausedEvent):
                console.print(f"\n[yellow]Paused: {event.step_name}[/]")
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
