"""
Steps Container with Executor HITL Example (Streaming)
=======================================================

A Steps container runs multiple inner steps sequentially, and one of
its inner steps has an agent with a tool that requires_confirmation=True
(executor HITL).

Flow:
  gather_data -> Steps([preprocess, analysis_agent, postprocess]) -> report
                                      |
                                      v
                                analysis_agent pauses for confirmation

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/executor_hitl/06_agent_confirmation_in_steps_container.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.run.workflow import (
    StepExecutorPausedEvent,
    WorkflowCompletedEvent,
)
from agno.tools import tool
from agno.workflow.step import Step
from agno.workflow.steps import Steps
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
def run_deep_scan(target: str) -> str:
    """Run a deep security scan on the target. This is a resource-intensive operation.

    Args:
        target: The target system or component to scan.
    """
    return (
        f"Deep scan of '{target}' complete:\n"
        "- 0 critical vulnerabilities\n"
        "- 2 warnings\n"
        "- 15 informational findings"
    )


scan_agent = Agent(
    name="SecurityScanAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[run_deep_scan],
    instructions=(
        "You perform security scans. You MUST always call the run_deep_scan tool "
        "exactly once with the target from the input. Never ask for clarification."
    ),
    db=db,
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Simple executor functions
# ---------------------------------------------------------------------------
def gather_data(step_input: StepInput) -> StepOutput:
    topic = step_input.input or "system"
    return StepOutput(content=f"Data gathered for: {topic}")


def preprocess(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "unknown-target"
    return StepOutput(content=f"Preprocessing complete. Target to scan: {prev}")


def postprocess(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Postprocessing: scan results formatted\n{prev}")


def generate_report(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "No scan results"
    return StepOutput(content=f"=== SECURITY REPORT ===\n\n{prev}\n\nReport complete.")


# ---------------------------------------------------------------------------
# Workflow with Steps container containing an agent with HITL
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="StepsExecutorHITL",
    db=db,
    steps=[
        Step(name="gather_data", executor=gather_data),
        Steps(
            name="scan_pipeline",
            steps=[
                Step(name="preprocess", executor=preprocess),
                Step(name="deep_scan", agent=scan_agent),
                Step(name="postprocess", executor=postprocess),
            ],
        ),
        Step(name="report", executor=generate_report),
    ],
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Run with streaming
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console.print(
        "[bold]Starting workflow with Steps container + Executor HITL...[/]\n"
    )

    paused_response = None

    for event in workflow.run("production-api", stream=True):
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
            if isinstance(event, WorkflowCompletedEvent):
                console.print("\n[bold green]Workflow completed![/]")
            elif hasattr(event, "content") and event.content:
                print(event.content, end="", flush=True)

    # Final output
    session = workflow.get_session()
    if session and session.runs:
        final_run = session.runs[-1]
        console.print(f"\n\n[bold green]Final output:[/] {final_run.content}")
