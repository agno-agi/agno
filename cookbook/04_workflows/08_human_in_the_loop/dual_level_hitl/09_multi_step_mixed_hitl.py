"""
Dual HITL: Multi-Step Workflow with Mixed HITL Types (Streaming)
=================================================================

A realistic multi-step workflow where each step has a different combination
of step-level and executor-level HITL:

  Step 1 "gather_requirements": requires_user_input (collect project details)
      -> No executor HITL (simple function step)
  Step 2 "generate_plan": requires_confirmation (confirm before agent runs)
      -> Agent tool has requires_confirmation (confirm the plan creation tool)
  Step 3 "review_plan": requires_output_review (review agent output after execution)
      -> Agent tool has requires_confirmation (confirm the finalize tool)

This demonstrates a real-world pattern where different steps in the same
workflow have different HITL requirements at both levels.

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/dual_level_hitl/09_multi_step_mixed_hitl.py
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


# ---------------------------------------------------------------------------
# Step 1: Simple function that uses user input (no executor HITL)
# ---------------------------------------------------------------------------
def gather_requirements(step_input: StepInput) -> StepOutput:
    """Gather project requirements from user input."""
    user_data = (step_input.additional_data or {}).get("user_input", {})
    project = user_data.get("project_name", "Unknown Project")
    scope = user_data.get("scope", "Not specified")
    return StepOutput(content=f"Requirements gathered for '{project}': scope={scope}")


# ---------------------------------------------------------------------------
# Step 2: Agent that creates a project plan
# ---------------------------------------------------------------------------
@tool(requires_confirmation=True)
def create_plan(project: str, tasks: str) -> str:
    """Create a project plan with tasks.

    Args:
        project: Project name.
        tasks: Comma-separated list of tasks.
    """
    task_list = [t.strip() for t in tasks.split(",")]
    return f"Plan for '{project}':\n" + "\n".join(f"  - {t}" for t in task_list)


planner_agent = Agent(
    name="PlannerAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[create_plan],
    instructions=(
        "You create project plans. Use the create_plan tool EXACTLY ONCE. "
        "Extract the project name from context and create 3-5 relevant tasks."
    ),
    db=db,
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Step 3: Agent that finalizes and publishes the plan
# ---------------------------------------------------------------------------
@tool(requires_confirmation=True)
def finalize_plan(plan: str) -> str:
    """Finalize and publish a project plan.

    Args:
        plan: The plan content to finalize.
    """
    return f"FINALIZED: {plan}"


reviewer_agent = Agent(
    name="ReviewerAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[finalize_plan],
    instructions=(
        "You review and finalize project plans. Use the finalize_plan tool EXACTLY ONCE "
        "with the plan from the previous step."
    ),
    db=db,
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="MultiStepMixedHITL",
    db=db,
    steps=[
        Step(
            name="gather_requirements",
            executor=gather_requirements,
            requires_user_input=True,
            user_input_message="Provide project details:",
            user_input_schema=[
                {
                    "name": "project_name",
                    "field_type": "text",
                    "description": "Project name",
                    "required": True,
                },
                {
                    "name": "scope",
                    "field_type": "text",
                    "description": "Project scope",
                    "required": True,
                },
            ],
        ),
        Step(
            name="generate_plan",
            agent=planner_agent,
            requires_confirmation=True,
            confirmation_message="Ready to generate the project plan. Proceed?",
        ),
        Step(
            name="review_plan",
            agent=reviewer_agent,
            requires_output_review=True,
            output_review_message="Review the finalized plan before publishing.",
            on_reject=OnReject.retry,
            hitl_max_retries=2,
        ),
    ],
    telemetry=False,
)


# ---------------------------------------------------------------------------
# HITL resolution helpers
# ---------------------------------------------------------------------------
def resolve_user_input(run_output):
    for req in (run_output.step_requirements or [])[-1:]:
        if req.requires_user_input and not req.requires_executor_input:
            console.print(f"  [dim]{req.user_input_message}[/]")
            user_input = {}
            if req.user_input_schema:
                for field in req.user_input_schema:
                    val = Prompt.ask(f"  {field.name}")
                    field.value = val
                    user_input[field.name] = val
            req.user_input = user_input
            req.confirmed = True


def resolve_confirmation(run_output):
    for req in (run_output.step_requirements or [])[-1:]:
        if (
            req.requires_confirmation
            and not req.requires_executor_input
            and not req.requires_output_review
        ):
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


def resolve_output_review(run_output):
    for req in (run_output.step_requirements or [])[-1:]:
        if req.requires_output_review and not req.requires_executor_input:
            console.print(f"  [dim]{req.output_review_message}[/]")
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


def resolve_pause(run_output):
    """Route to the appropriate resolver based on requirement type."""
    # Only check the LAST (active) requirement — earlier ones are resolved history
    _active = (run_output.step_requirements or [])[-1:]
    has_executor = any(r.requires_executor_input for r in _active)
    has_user_input = any(
        r.requires_user_input and not r.requires_executor_input for r in _active
    )
    has_review = any(
        r.requires_output_review
        and r.confirmed is None
        and not r.requires_executor_input
        for r in _active
    )
    has_confirm = any(
        r.requires_confirmation
        and not r.requires_executor_input
        and not r.requires_output_review
        for r in _active
    )

    if has_executor:
        label = "executor"
    elif has_user_input:
        label = "user-input"
    elif has_review:
        label = "output-review"
    elif has_confirm:
        label = "confirmation"
    else:
        label = "unknown"

    return label


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console.print("[bold]Multi-Step Mixed HITL Workflow[/]\n")
    console.print("Step 1: User input (project details)")
    console.print("Step 2: Confirmation + tool confirmation (plan generation)")
    console.print("Step 3: Tool confirmation + output review (plan finalization)\n")

    pause_count = 0
    for event in workflow.run("Start project planning", stream=True):
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
        label = resolve_pause(run_output)
        console.print(f"\n[bold magenta]--- Pause #{pause_count} ({label}) ---[/]")

        if label == "executor":
            resolve_executor_pause(run_output)
        elif label == "user-input":
            resolve_user_input(run_output)
        elif label == "output-review":
            resolve_output_review(run_output)
        elif label == "confirmation":
            resolve_confirmation(run_output)
        else:
            # Catch-all: auto-confirm any unresolved requirements from retry flows
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

    console.print(f"\n[bold green]Done after {pause_count} pause(s)![/]")
    if run_output:
        console.print(f"[bold green]Final output:[/] {run_output.content}")
