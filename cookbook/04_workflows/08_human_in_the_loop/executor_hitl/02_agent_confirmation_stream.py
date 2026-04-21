"""
Agent Confirmation in Workflow Step (Streaming)
=================================================

Same as 01_agent_confirmation but uses streaming. When the agent pauses,
a StepExecutorPausedEvent is emitted in the stream.

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/executor_hitl/02_agent_confirmation_stream.py
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


@tool(requires_confirmation=True)
def get_the_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city to get weather for.
    """
    return f"It is currently 70 degrees and cloudy in {city}"


weather_agent = Agent(
    name="WeatherAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_the_weather],
    instructions="You provide weather information. Always use the get_the_weather tool.",
    db=db,
    telemetry=False,
)


def save_result(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "no previous content"
    return StepOutput(content=f"Result saved: {prev}")


workflow = Workflow(
    name="WeatherWorkflowStream",
    db=db,
    steps=[
        Step(name="get_weather", agent=weather_agent),
        Step(name="save", executor=save_result),
    ],
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Run with streaming
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for event in workflow.run("What is the weather in Tokyo?", stream=True):
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

    # Get run output from session (not from stream - WorkflowRunOutput is saved to session, not yielded)
    session = workflow.get_session()
    paused_response = session.runs[-1] if session and session.runs else None

    if paused_response and paused_response.is_paused:
        console.print("\n[bold yellow]Workflow is paused. Resolving requirements...[/]")

        for step_req in paused_response.step_requirements or []:
            if step_req.requires_executor_input:
                answer = (
                    Prompt.ask(
                        f"Approve tool call from {step_req.executor_name}?",
                        choices=["y", "n"],
                        default="y",
                    )
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

        # Continue with streaming - tokens are streamed chunk by chunk
        console.print("\n[bold]Continuing workflow...[/]")
        for event in workflow.continue_run(paused_response, stream=True):
            if isinstance(event, WorkflowCompletedEvent):
                console.print("\n\n[bold green]Workflow completed![/]")
            elif hasattr(event, "content") and event.content:
                print(event.content, end="", flush=True)

        # Get final output from the session
        session = workflow.get_session()
        if session and session.runs:
            final_run = session.runs[-1]
            console.print(f"[bold green]Final output:[/] {final_run.content}")
