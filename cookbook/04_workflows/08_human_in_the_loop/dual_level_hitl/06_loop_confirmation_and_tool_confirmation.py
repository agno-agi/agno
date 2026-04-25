"""
Dual HITL: Loop Confirmation + Executor Tool Confirmation (Streaming)
======================================================================

Two HITL levels with a Loop primitive:
  Pause 1 (loop-level): Loop has requires_confirmation=True -> user confirms
          before the loop starts executing
  Pause 2 (executor-level): On each iteration, the agent's tool has
          requires_confirmation=True -> user confirms the tool call

Note: Loop iteration review (requires_iteration_review) and executor-level
HITL cannot currently be combined because executor HITL interrupts the Loop's
internal iteration tracking. This cookbook demonstrates Loop *confirmation*
(pre-execution gate) + executor tool confirmation instead.

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/dual_level_hitl/06_loop_confirmation_and_tool_confirmation.py
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
from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

iteration_counter = 0


@tool(requires_confirmation=True)
def publish_draft(title: str, content: str) -> str:
    """Publish a draft to the blog. Call this exactly once.

    Args:
        title: The blog post title.
        content: The blog post content.
    """
    global iteration_counter
    iteration_counter += 1
    return f"[v{iteration_counter}] Published '{title}': {content[:80]}..."


writer_agent = Agent(
    name="WriterAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[publish_draft],
    instructions=(
        "You are a writer. Write a short blog post and call publish_draft EXACTLY ONCE "
        "with the title and content. Do NOT call any tool more than once."
    ),
    db=db,
    telemetry=False,
)


workflow = Workflow(
    name="LoopConfirmAndToolConfirm",
    db=db,
    steps=[
        Loop(
            name="publish_loop",
            steps=[Step(name="write_and_publish", agent=writer_agent)],
            max_iterations=3,
            # Loop-level HITL: confirm before loop starts
            requires_confirmation=True,
            confirmation_message="This will run a publishing loop (up to 3 iterations). Proceed?",
        ),
    ],
    telemetry=False,
)


def resolve_step_pause(run_output):
    """Resolve step/loop-level confirmation."""
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
                console.print("  [dim]Loop skipped[/]")


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
                    console.print(f"  Tool: [bold blue]{t_name}[/]")
                    console.print(f"  Args: [dim]{t_args}[/]")

            answer = (
                Prompt.ask("  Approve publish?", choices=["y", "n"], default="y")
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
    console.print("[bold]Dual HITL: Loop Confirmation + Tool Confirmation[/]\n")
    console.print("First confirm the loop, then confirm each tool call per iteration\n")

    pause_count = 0
    for event in workflow.run(
        "Write and publish a short blog post about AI safety", stream=True
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
        # Only check the LAST (active) requirement — earlier ones are resolved history
        _active = (run_output.step_requirements or [])[-1:]
        has_executor = any(r.requires_executor_input for r in _active)
        label = "executor" if has_executor else "loop-confirmation"
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
