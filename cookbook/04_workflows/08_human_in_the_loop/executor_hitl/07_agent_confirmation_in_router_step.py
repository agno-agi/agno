"""
Router with Executor HITL Example (Streaming)
===============================================

A Router selects which branch to execute, and the chosen branch has an
agent with a tool that requires_confirmation=True (executor HITL).

The Router uses a selector function to auto-pick the "deep_analysis" branch,
which contains an agent whose tool pauses for confirmation.

Flow:
  gather_data -> Router(selector -> deep_analysis_agent) -> report
                                         |
                                         v
                              deep_analysis_agent pauses
                              for confirmation

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/executor_hitl/07_agent_confirmation_in_router_step.py
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
from agno.workflow.router import Router
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
def run_deep_analysis(subject: str) -> str:
    """Run a deep analysis on the subject. This is a costly operation.

    Args:
        subject: The subject to analyze deeply.
    """
    return (
        f"Deep analysis of '{subject}' complete:\n"
        "- 200 data points analyzed\n"
        "- 5 key insights extracted\n"
        "- Confidence: 97%"
    )


deep_analysis_agent = Agent(
    name="DeepAnalysisAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[run_deep_analysis],
    instructions=(
        "You perform deep data analysis. "
        "Always use the run_deep_analysis tool with the subject from the input."
    ),
    db=db,
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Simple executor functions
# ---------------------------------------------------------------------------
def gather_data(step_input: StepInput) -> StepOutput:
    topic = step_input.input or "general"
    return StepOutput(content=f"Data gathered for: {topic}")


def fast_check(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Fast check: all systems nominal")


def generate_report(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "No analysis"
    return StepOutput(content=f"=== ANALYSIS REPORT ===\n\n{prev}\n\nReport complete.")


# ---------------------------------------------------------------------------
# Selector function that always picks "deep_analysis" to demonstrate
# executor HITL within a Router branch.
# ---------------------------------------------------------------------------
def always_deep_analysis(step_input: StepInput) -> str:
    """Always route to deep_analysis to trigger the executor HITL."""
    return "deep_analysis"


# ---------------------------------------------------------------------------
# Workflow with Router containing an agent with HITL
# The Router uses a selector function to auto-pick the route.
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="RouterExecutorHITL",
    db=db,
    steps=[
        Step(name="gather_data", executor=gather_data),
        Router(
            name="analysis_router",
            choices=[
                Step(name="fast_check", executor=fast_check),
                Step(name="deep_analysis", agent=deep_analysis_agent),
            ],
            selector=always_deep_analysis,
        ),
        Step(name="report", executor=generate_report),
    ],
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Run with streaming
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console.print("[bold]Starting workflow with Router + Executor HITL...[/]\n")

    for event in workflow.run("quarterly revenue", stream=True):
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
