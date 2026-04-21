"""
Dual HITL: Router Output Review + Executor Tool Confirmation (Streaming)
=========================================================================

Two HITL levels on a Router:
  Pause 1 (executor-level): Agent's tool has requires_confirmation=True
          -> user confirms the tool call DURING execution
  Pause 2 (router-level): Router has requires_output_review=True
          -> AFTER the selected branch completes, user reviews the output

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/dual_level_hitl/08_router_output_review_and_tool_confirmation.py
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
from agno.workflow.types import OnReject, StepInput
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


@tool(requires_confirmation=True)
def generate_report(report_type: str, data: str) -> str:
    """Generate a formatted report.

    Args:
        report_type: Type of report (summary, detailed, executive).
        data: The data to include in the report.
    """
    return f"[{report_type.upper()} REPORT]\n{data}\n---\nGenerated automatically."


summary_agent = Agent(
    name="SummaryAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[generate_report],
    instructions=(
        "You generate summary reports. Always call generate_report with "
        "report_type='summary'. Call it exactly once."
    ),
    db=db,
    telemetry=False,
)

detailed_agent = Agent(
    name="DetailedAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[generate_report],
    instructions=(
        "You generate detailed reports. Always call generate_report with "
        "report_type='detailed'. Call it exactly once."
    ),
    db=db,
    telemetry=False,
)


def pick_report_type(step_input: StepInput) -> list:
    """Selector: picks summary unless 'detailed' is mentioned."""
    text = str(step_input.input or "").lower()
    if "detailed" in text:
        return [Step(name="detailed_report", agent=detailed_agent)]
    return [Step(name="summary_report", agent=summary_agent)]


workflow = Workflow(
    name="RouterReviewAndToolConfirm",
    db=db,
    steps=[
        Router(
            name="report_router",
            choices=[
                Step(name="summary_report", agent=summary_agent),
                Step(name="detailed_report", agent=detailed_agent),
            ],
            selector=pick_report_type,
            requires_output_review=True,
            output_review_message="Review the generated report before finalizing.",
            on_reject=OnReject.retry,
            hitl_max_retries=2,
        ),
    ],
    telemetry=False,
)


def resolve_executor_pause(run_output):
    for req in run_output.step_requirements or []:
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


def resolve_output_review(run_output):
    for req in run_output.step_requirements or []:
        if req.requires_output_review and not req.requires_executor_input:
            console.print(
                f"  [dim]{req.output_review_message or 'Review the output'}[/]"
            )
            if req.step_output:
                console.print(f"  Output: {req.step_output.content}")
            answer = (
                Prompt.ask("  Approve?", choices=["y", "n"], default="y")
                .strip()
                .lower()
            )
            if answer == "y":
                req.confirm()
            else:
                feedback = Prompt.ask("  Feedback (optional)", default="")
                req.reject(feedback=feedback if feedback else None)


if __name__ == "__main__":
    console.print("[bold]Dual HITL: Router Output Review + Tool Confirmation[/]\n")
    console.print("1. Agent calls generate_report tool -> you confirm")
    console.print("2. After completion -> you review the report output\n")

    pause_count = 0
    for event in workflow.run(
        "Generate a summary report on Q4 sales performance", stream=True
    ):
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
        has_executor = any(
            r.requires_executor_input for r in (run_output.step_requirements or [])
        )
        has_review = any(
            r.requires_output_review
            and r.confirmed is None
            and not r.requires_executor_input
            for r in (run_output.step_requirements or [])
        )
        label = (
            "executor"
            if has_executor
            else ("output-review" if has_review else "confirmation")
        )
        console.print(f"\n[bold magenta]--- Pause #{pause_count} ({label}) ---[/]")

        if has_executor:
            resolve_executor_pause(run_output)
        elif has_review:
            resolve_output_review(run_output)
        else:
            # Router retry creates a re-route requirement — user picks a new branch
            for req in run_output.step_requirements or []:
                if req.requires_route_selection and req.needs_route_selection:
                    console.print("  Re-route: pick a different branch")
                    console.print(f"  Available: {req.available_choices}")
                    choice = Prompt.ask("  Pick a route", choices=req.available_choices)
                    req.selected_choices = [choice]
                    req.confirmed = True
                elif not req.is_resolved:
                    req.confirm()

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
