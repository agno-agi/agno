"""
Loop with Executor HITL Example (Streaming)
=============================================

A Loop repeatedly runs steps, and one of its inner steps has an agent
with a tool that requires_confirmation=True (executor HITL).

Flow:
  gather_data -> Loop(steps=[analysis_agent]) -> report
                    |
                    v
              analysis_agent pauses for confirmation each iteration

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/executor_hitl/05_agent_confirmation_in_loop_step.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.run.workflow import (
    StepExecutorPausedEvent,
    WorkflowCompletedEvent,
)
from agno.tools import tool
from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


# ---------------------------------------------------------------------------
# Tool with executor-level HITL
# ---------------------------------------------------------------------------
@tool(requires_confirmation=True)
def run_batch_analysis(batch_id: str) -> str:
    """Run analysis on a batch of data. This is an expensive operation.

    Args:
        batch_id: The batch identifier to analyze.
    """
    return (
        f"Batch '{batch_id}' analysis complete:\n"
        "- 120 records processed\n"
        "- 3 anomalies detected\n"
        "- Quality score: 94%"
    )


analysis_agent = Agent(
    name="BatchAnalysisAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[run_batch_analysis],
    instructions=(
        "You analyze data batches. "
        "Always use the run_batch_analysis tool with the batch_id from the input."
    ),
    db=db,
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Simple executor functions
# ---------------------------------------------------------------------------
def gather_data(step_input: StepInput) -> StepOutput:
    topic = step_input.input or "general data"
    return StepOutput(content=f"Data gathered for: {topic}")


def generate_report(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "No analysis"
    return StepOutput(content=f"=== FINAL REPORT ===\n\n{prev}\n\nReport complete.")


# ---------------------------------------------------------------------------
# Workflow with Loop containing an agent with HITL
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="LoopExecutorHITL",
    db=db,
    steps=[
        Step(name="gather_data", executor=gather_data),
        Loop(
            name="batch_processing",
            steps=[Step(name="batch_analysis", agent=analysis_agent)],
            max_iterations=1,
        ),
        Step(name="report", executor=generate_report),
    ],
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Run with streaming
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console.print("[bold]Starting workflow with Loop + Executor HITL...[/]\n")

    paused_response = None

    for event in workflow.run("batch-001", stream=True):
        if isinstance(event, StepExecutorPausedEvent):
            console.print(
                f"\n[bold yellow]StepExecutorPausedEvent:[/]\n"
                f"  Step: {event.step_name}\n"
                f"  Executor: {event.executor_name} ({event.executor_type})\n"
                f"  Requirements: {len(event.executor_requirements or [])}"
            )
        elif isinstance(event, WorkflowCompletedEvent):
            console.print("\n[bold green]Workflow completed![/]")
        elif hasattr(event, "content") and event.content:
            print(event.content, end="", flush=True)

    # Check if workflow is paused
    session = workflow.get_session()
    if session and session.runs:
        paused_response = session.runs[-1]

    if paused_response and paused_response.is_paused:
        console.print(
            f"\n[bold yellow]Workflow paused (step: {paused_response.paused_step_name})[/]"
        )

        for step_req in paused_response.step_requirements or []:
            if step_req.requires_executor_input:
                console.print(
                    f"  Agent: {step_req.executor_name} ({step_req.executor_type})"
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
                    Prompt.ask("  Approve tool call?", choices=["y", "n"], default="y")
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

        # Continue with streaming
        console.print("\n[bold]Continuing workflow...[/]")
        for event in workflow.continue_run(paused_response, stream=True):
            if isinstance(event, StepExecutorPausedEvent):
                console.print(
                    f"\n[bold yellow]StepExecutorPausedEvent (chained):[/]\n"
                    f"  Step: {event.step_name}\n"
                    f"  Executor: {event.executor_name}"
                )
            elif isinstance(event, WorkflowCompletedEvent):
                console.print("\n[bold green]Workflow completed![/]")
            elif hasattr(event, "content") and event.content:
                print(event.content, end="", flush=True)

    # Final output
    session = workflow.get_session()
    if session and session.runs:
        final_run = session.runs[-1]
        console.print(f"\n\n[bold green]Final output:[/] {final_run.content}")
