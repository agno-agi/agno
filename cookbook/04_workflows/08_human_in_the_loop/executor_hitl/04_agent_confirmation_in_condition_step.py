"""
Condition with Executor HITL Example (Streaming)
==================================================

A Condition evaluates which branch to take, and the agent inside the
chosen branch has a tool with requires_confirmation=True (executor HITL).

Flow:
  gather_data -> Condition(evaluator) -> report
                    |           |
                    v           v
              detailed       quick_summary
              (agent w/
              HITL tool)

Usage:
    .venvs/demo/bin/python libs/agno/agno/test.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.run.workflow import (
    StepExecutorPausedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
)
from agno.tools import tool
from agno.workflow.condition import Condition
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
def run_detailed_analysis(topic: str) -> str:
    """Run a detailed analysis on the given topic. This is an expensive operation.

    Args:
        topic: The topic to analyze in detail.
    """
    return (
        f"Detailed analysis for '{topic}':\n"
        "- Comprehensive data review completed\n"
        "- All edge cases examined\n"
        "- 47 data points processed"
    )


analysis_agent = Agent(
    name="AnalysisAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[run_detailed_analysis],
    instructions=(
        "You perform detailed data analysis. "
        "Always use the run_detailed_analysis tool with the user's topic."
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


def quick_summary(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Quick summary: basic metrics computed in 1 minute")


def generate_report(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "No analysis"
    return StepOutput(content=f"=== FINAL REPORT ===\n\n{prev}\n\nReport complete.")


# ---------------------------------------------------------------------------
# Workflow
# The Condition always evaluates to True (so the if-branch runs),
# and that branch contains an agent with a HITL tool.
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="ConditionExecutorHITL",
    db=db,
    steps=[
        Step(name="gather_data", executor=gather_data),
        Condition(
            name="analysis_decision",
            evaluator=True,
            steps=[Step(name="detailed_analysis", agent=analysis_agent)],
            else_steps=[Step(name="quick_summary", executor=quick_summary)],
        ),
        Step(name="report", executor=generate_report),
    ],
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Run with streaming
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console.print("[bold]Starting workflow with Condition + Executor HITL...[/]\n")

    for event in workflow.run("Q4 sales performance", stream=True):
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

    # Get the paused response from the session (persisted to DB)
    paused_response = None
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
            if isinstance(event, WorkflowCompletedEvent):
                console.print("\n[bold green]Workflow completed![/]")
            elif isinstance(event, WorkflowRunOutput):
                pass
            elif hasattr(event, "content") and event.content:
                print(event.content, end="", flush=True)

    # Final output
    session = workflow.get_session()
    if session and session.runs:
        final_run = session.runs[-1]
        console.print(f"\n\n[bold green]Final output:[/] {final_run.content}")
