"""
Agent User Input in Workflow Step (Streaming)
==============================================

An agent's tool has requires_user_input=True, so it pauses for user-provided
values before execution. The workflow propagates this pause via
StepExecutorPausedEvent in the stream.

Usage:
    .venvs/demo/bin/python libs/agno/agno/test.py
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
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


@tool(requires_user_input=True, user_input_fields=["recipient"])
def send_money(amount: float, recipient: str, note: str) -> str:
    """Send money to a recipient.

    Args:
        amount: The amount of money to send.
        recipient: The recipient to send money to (provided by user).
        note: A note to include with the transfer.
    """
    return f"Sent ${amount} to {recipient}: {note}"


transfer_agent = Agent(
    name="TransferAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[send_money],
    instructions="You handle money transfers. Always use the send_money tool.",
    db=db,
    telemetry=False,
)


def save_result(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "no previous content"
    return StepOutput(content=f"Result saved: {prev}")


workflow = Workflow(
    name="TransferWorkflowStream",
    db=db,
    steps=[
        Step(name="transfer", agent=transfer_agent),
        Step(name="save", executor=save_result),
    ],
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run with streaming
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console.print("[bold]Starting workflow with Agent User Input HITL...[/]\n")

    for event in workflow.run("Send $50 with note 'lunch money'", stream=True):
        if isinstance(event, StepExecutorPausedEvent):
            console.print(
                f"\n[bold yellow]StepExecutorPausedEvent received![/]\n"
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

                        # Show user_input_schema fields
                        schema = (
                            tool_exec.get("user_input_schema", [])
                            if isinstance(tool_exec, dict)
                            else getattr(tool_exec, "user_input_schema", [])
                        )
                        if schema:
                            console.print("  [bold]User input required for:[/]")
                            for field in schema:
                                fname = (
                                    field.get("name", "?")
                                    if isinstance(field, dict)
                                    else getattr(field, "name", "?")
                                )
                                console.print(f"    - {fname}")

                # Provide user input for each requirement
                for executor_req in step_req.executor_requirements or []:
                    if isinstance(executor_req, dict):
                        # Dict-based requirement: fill user_input_schema values
                        schema = executor_req.get("user_input_schema", [])
                        if schema:
                            for field in schema:
                                fname = (
                                    field.get("name", "?")
                                    if isinstance(field, dict)
                                    else getattr(field, "name", "?")
                                )
                                value = Prompt.ask(f"  Enter value for '{fname}'")
                                if isinstance(field, dict):
                                    field["value"] = value
                                else:
                                    field.value = value
                            # Also update tool_execution's user_input_schema
                            tool_exec = executor_req.get("tool_execution", {})
                            if tool_exec and isinstance(tool_exec, dict):
                                tool_schema = tool_exec.get("user_input_schema", [])
                                for field in tool_schema:
                                    fname = (
                                        field.get("name", "?")
                                        if isinstance(field, dict)
                                        else getattr(field, "name", "?")
                                    )
                                    # Find matching value from the requirement schema
                                    for req_field in schema:
                                        req_fname = (
                                            req_field.get("name", "?")
                                            if isinstance(req_field, dict)
                                            else getattr(req_field, "name", "?")
                                        )
                                        if req_fname == fname:
                                            val = (
                                                req_field.get("value")
                                                if isinstance(req_field, dict)
                                                else getattr(req_field, "value", None)
                                            )
                                            if isinstance(field, dict):
                                                field["value"] = val
                                            else:
                                                field.value = val
                    else:
                        # Object-based requirement: use provide_user_input
                        if (
                            hasattr(executor_req, "needs_user_input")
                            and executor_req.needs_user_input
                        ):
                            user_values = {}
                            for field in executor_req.user_input_schema or []:
                                value = Prompt.ask(f"  Enter value for '{field.name}'")
                                user_values[field.name] = value
                            executor_req.provide_user_input(user_values)

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
