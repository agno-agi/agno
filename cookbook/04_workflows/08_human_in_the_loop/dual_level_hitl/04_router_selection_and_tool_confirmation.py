"""
Dual HITL: Router User Selection + Executor Tool Confirmation (Streaming)
==========================================================================

Two HITL levels across a Router primitive:
  Pause 1 (router-level): Router has requires_user_input=True -> user picks which route
  Pause 2 (executor-level): The agent on the chosen route has a tool with
          requires_confirmation=True -> user confirms the tool call

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/dual_level_hitl/04_router_selection_and_tool_confirmation.py
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
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


@tool(requires_confirmation=True)
def send_email(to: str, subject: str) -> str:
    """Send an email notification.

    Args:
        to: Recipient email address.
        subject: Email subject line.
    """
    return f"Email sent to {to}: {subject}"


@tool(requires_confirmation=True)
def send_sms(phone: str, message: str) -> str:
    """Send an SMS notification.

    Args:
        phone: Phone number.
        message: SMS message body.
    """
    return f"SMS sent to {phone}: {message}"


@tool(requires_confirmation=True)
def post_to_slack(channel: str, message: str) -> str:
    """Post a message to a Slack channel.

    Args:
        channel: Slack channel name.
        message: Message to post.
    """
    return f"Posted to #{channel}: {message}"


email_agent = Agent(
    name="EmailAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[send_email],
    instructions="Send email notifications. Always use send_email.",
    db=db,
    telemetry=False,
)

sms_agent = Agent(
    name="SMSAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[send_sms],
    instructions="Send SMS notifications. Always use send_sms.",
    db=db,
    telemetry=False,
)

slack_agent = Agent(
    name="SlackAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[post_to_slack],
    instructions="Post to Slack. Always use post_to_slack.",
    db=db,
    telemetry=False,
)


workflow = Workflow(
    name="RouterAndToolConfirm",
    db=db,
    steps=[
        Router(
            name="notification_router",
            choices=[
                Step(name="email", agent=email_agent),
                Step(name="sms", agent=sms_agent),
                Step(name="slack", agent=slack_agent),
            ],
            # Router-level HITL: user picks which notification channel
            requires_user_input=True,
            user_input_message="Which notification channel should we use?",
        ),
    ],
    telemetry=False,
)


def resolve_router_pause(run_output):
    """Resolve router-level user selection."""
    for req in (run_output.step_requirements or [])[-1:]:
        if req.requires_route_selection:
            console.print(f"  [dim]{req.user_input_message or 'Select a route'}[/]")
            console.print(f"  Available: {req.available_choices}")
            choice = Prompt.ask("  Your choice", choices=req.available_choices)
            req.selected_choices = [choice]
            req.confirmed = True


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
    console.print("[bold]Dual HITL: Router Selection + Tool Confirmation[/]\n")
    console.print("First you pick a notification channel, then confirm the tool call\n")

    pause_count = 0
    for event in workflow.run("Notify the team about the deployment", stream=True):
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
        has_route = any(r.requires_route_selection for r in _active)
        label = "executor" if has_executor else ("router" if has_route else "step")
        console.print(
            f"\n[bold magenta]--- Pause #{pause_count} ({label}-level) ---[/]"
        )

        if has_executor:
            resolve_executor_pause(run_output)
        elif has_route:
            resolve_router_pause(run_output)

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
