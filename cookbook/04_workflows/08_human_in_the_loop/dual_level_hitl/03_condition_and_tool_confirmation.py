"""
Dual HITL: Condition Confirmation + Executor Tool Confirmation (Streaming)
===========================================================================

Two HITL levels across a Condition primitive:
  Pause 1 (condition-level): Condition has requires_confirmation=True -> user decides
          whether to execute the if-branch or the else-branch
  Pause 2 (executor-level): The agent inside the chosen branch has a tool with
          requires_confirmation=True -> user confirms the tool call

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/dual_level_hitl/03_condition_and_tool_confirmation.py
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
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import OnReject, StepInput
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


@tool(requires_confirmation=True)
def deploy_to_production(service: str) -> str:
    """Deploy a service to production.

    Args:
        service: The service name to deploy.
    """
    return f"Deployed {service} to production successfully"


@tool(requires_confirmation=True)
def deploy_to_staging(service: str) -> str:
    """Deploy a service to staging.

    Args:
        service: The service name to deploy.
    """
    return f"Deployed {service} to staging successfully"


prod_agent = Agent(
    name="ProdDeployer",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[deploy_to_production],
    instructions="You deploy services to production. Always use deploy_to_production.",
    db=db,
    telemetry=False,
)

staging_agent = Agent(
    name="StagingDeployer",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[deploy_to_staging],
    instructions="You deploy services to staging. Always use deploy_to_staging.",
    db=db,
    telemetry=False,
)


def is_production_ready(step_input: StepInput) -> bool:
    """Evaluator: always returns True so the condition triggers the if-branch."""
    return True


workflow = Workflow(
    name="ConditionAndToolConfirm",
    db=db,
    steps=[
        Condition(
            name="deploy_gate",
            evaluator=is_production_ready,
            # If-branch: deploy to production
            steps=[Step(name="deploy_prod", agent=prod_agent)],
            # Else-branch: deploy to staging
            else_steps=[Step(name="deploy_staging", agent=staging_agent)],
            # Condition-level HITL: user decides if they want the if-branch
            requires_confirmation=True,
            confirmation_message="Production deployment is ready. Deploy to production?",
            on_reject=OnReject.else_branch,  # On reject -> else branch (staging)
        ),
    ],
    telemetry=False,
)


def resolve_step_pause(run_output):
    """Resolve step/condition-level confirmation."""
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
                console.print(
                    "  [dim]Rejected -> will execute else-branch (staging)[/]"
                )


def resolve_executor_pause(run_output):
    """Resolve executor-level tool confirmation."""
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
    console.print("[bold]Dual HITL: Condition Confirmation + Tool Confirmation[/]\n")
    console.print("Confirm -> production branch, Reject -> staging branch")
    console.print("Either branch has an agent with a requires_confirmation tool\n")

    pause_count = 0
    for event in workflow.run("Deploy the auth-service", stream=True):
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
        console.print(
            f"\n[bold magenta]--- Pause #{pause_count} ({'executor' if has_executor else 'condition'}-level) ---[/]"
        )

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
