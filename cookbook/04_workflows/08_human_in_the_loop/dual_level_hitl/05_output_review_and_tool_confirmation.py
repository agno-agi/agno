"""
Dual HITL: Post-Execution Output Review + Executor Tool Confirmation (Streaming)
==================================================================================

Two HITL levels on a single step - one pre-execution, one post-execution:
  Pause 1 (executor-level): Agent's tool has requires_confirmation=True
          -> user confirms the tool call DURING execution
  Pause 2 (step-level): Step has requires_output_review=True
          -> AFTER the agent completes, user reviews the output and can
             approve, reject (retry with feedback), or edit

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/dual_level_hitl/05_output_review_and_tool_confirmation.py
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
from agno.workflow.types import OnReject, StepInput, StepOutput
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


@tool(requires_confirmation=True)
def query_database(query: str) -> str:
    """Run a database query.

    Args:
        query: The SQL query to execute.
    """
    return f"Query results for: {query}\n| id | name    | status |\n| 1  | Alice   | active |\n| 2  | Bob     | inactive |"


analyst_agent = Agent(
    name="DataAnalyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[query_database],
    instructions=(
        "You are a data analyst. You MUST always use the query_database tool to fetch data. "
        "Never ask the user for more details - just construct a reasonable SQL query and run it. "
        "After getting results, summarize them clearly."
    ),
    db=db,
    telemetry=False,
)


def save_report(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "no data"
    return StepOutput(content=f"Report saved: {prev}")


workflow = Workflow(
    name="OutputReviewAndToolConfirm",
    db=db,
    steps=[
        Step(
            name="analyze_data",
            agent=analyst_agent,
            # Post-execution review: user reviews agent output after it completes
            requires_output_review=True,
            output_review_message="Review the analysis before saving the report.",
            on_reject=OnReject.retry,
            hitl_max_retries=2,
        ),
        Step(name="save_report", executor=save_report),
    ],
    telemetry=False,
)


def resolve_executor_pause(run_output):
    """Resolve executor-level tool confirmation (active requirement only)."""
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
                Prompt.ask("  Approve query?", choices=["y", "n"], default="y")
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
    """Resolve step-level post-execution output review (active requirement only)."""
    for req in (run_output.step_requirements or [])[-1:]:
        if req.requires_output_review and req.confirmed is None:
            console.print(
                f"  [dim]{req.output_review_message or 'Review the output'}[/]"
            )
            if req.step_output:
                console.print(f"  Output: {req.step_output.content}")
            answer = (
                Prompt.ask("  Approve output?", choices=["y", "n"], default="y")
                .strip()
                .lower()
            )
            if answer == "y":
                req.confirm()
            else:
                feedback = Prompt.ask("  Rejection feedback (optional)", default="")
                req.reject(feedback=feedback if feedback else None)


if __name__ == "__main__":
    console.print(
        "[bold]Dual HITL: Tool Confirmation + Post-Execution Output Review[/]\n"
    )
    console.print("1. Agent will ask to run a query -> you confirm the tool call")
    console.print("2. After agent completes -> you review the output\n")

    pause_count = 0
    for event in workflow.run("Analyze user activity data", stream=True):
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
        has_review = any(
            r.requires_output_review
            and r.confirmed is None
            and not r.requires_executor_input
            for r in _active
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
            # Catch-all: auto-confirm any remaining unresolved requirements
            for req in _active:
                if not req.is_resolved:
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
