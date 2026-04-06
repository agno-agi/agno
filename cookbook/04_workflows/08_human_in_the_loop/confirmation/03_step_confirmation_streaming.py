"""
Step Confirmation with Streaming

This example demonstrates how to pause a workflow for user confirmation
before executing a step, with streaming execution for real-time event updates.

Key differences from non-streaming:
1. workflow.run(..., stream=True) returns an Iterator of events
2. stream_events=True is required to receive StepStartedEvent/StepCompletedEvent
3. StepPausedEvent is emitted when a step requires confirmation
4. Get WorkflowRunOutput from session after streaming
5. Use workflow.continue_run(..., stream=True, stream_events=True) for consistent streaming

The user can either:
- Confirm: Step executes and workflow continues
- Reject with on_reject=OnReject.cancel (default): Workflow is cancelled
- Reject with on_reject=OnReject.skip: Step is skipped and workflow continues with next step
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.workflow import (
    StepCompletedEvent,
    StepPausedEvent,
    StepStartedEvent,
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowStartedEvent,
)
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# Create agents for each step
fetch_agent = Agent(
    name="Fetcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You fetch and summarize data. Return a brief summary of what data you would fetch.",
)

process_agent = Agent(
    name="Processor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You process data. Describe what processing you would do on the input.",
)

save_agent = Agent(
    name="Saver",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You save results. Confirm that you would save the processed data.",
)

# Create a workflow with a step that requires confirmation
# on_reject=OnReject.skip means if user rejects, skip this step and continue with next
workflow = Workflow(
    name="data_processing_streaming",
    db=SqliteDb(db_file="tmp/workflow_hitl_streaming.db"),
    steps=[
        Step(
            name="fetch_data",
            agent=fetch_agent,
        ),
        Step(
            name="process_data",
            agent=process_agent,
            requires_confirmation=True,
            confirmation_message="About to process sensitive data. Confirm?",
            on_reject=OnReject.skip,  # If rejected, skip this step and continue with save_results
        ),
        Step(
            name="save_results",
            agent=save_agent,
        ),
    ],
)


def handle_confirmation_hitl(run_output):
    """Handle confirmation HITL requirements."""
    if run_output.steps_requiring_confirmation:
        for requirement in run_output.steps_requiring_confirmation:
            print("\n" + "-" * 50)
            print(f"Step '{requirement.step_name}' requires confirmation")
            print(f"Message: {requirement.confirmation_message}")
            print("-" * 50)

            user_input = input("\nDo you want to continue? (yes/no): ").strip().lower()

            if user_input in ("yes", "y"):
                requirement.confirm()
                print("Step confirmed.")
            else:
                requirement.reject()
                print("Step rejected.")


def process_event_stream(event_stream):
    """Process events from a workflow stream."""
    for event in event_stream:
        if isinstance(event, WorkflowStartedEvent):
            print(f"[EVENT] Workflow started: {event.workflow_name}")

        elif isinstance(event, StepStartedEvent):
            print(f"[EVENT] Step started: {event.step_name}")

        elif isinstance(event, StepPausedEvent):
            print(f"[EVENT] Step paused: {event.step_name}")
            if event.requires_confirmation:
                print("        Reason: Requires confirmation")
            if event.confirmation_message:
                print(f"        Message: {event.confirmation_message}")

        elif isinstance(event, StepCompletedEvent):
            print(f"[EVENT] Step completed: {event.step_name}")
            if event.content:
                preview = (
                    str(event.content)[:60] + "..."
                    if len(str(event.content)) > 60
                    else str(event.content)
                )
                print(f"        Content: {preview}")

        elif isinstance(event, WorkflowCompletedEvent):
            print("\n[EVENT] Workflow completed!")

        elif isinstance(event, WorkflowCancelledEvent):
            print("\n[EVENT] Workflow cancelled!")
            if event.reason:
                print(f"        Reason: {event.reason}")


def main():
    print("=" * 60)
    print("Step Confirmation with Streaming")
    print("=" * 60)
    print("The 'process_data' step requires confirmation before execution.")
    print("You can confirm to proceed or reject to skip the step.")
    print("\nStarting workflow with streaming...\n")

    # Run with streaming - returns an iterator of events
    # stream=True enables streaming output, stream_events=True enables step events
    event_stream = workflow.run("Process user data", stream=True, stream_events=True)

    # Process initial events
    process_event_stream(event_stream)

    # Get run output from session
    session = workflow.get_session()
    run_output = session.runs[-1] if session and session.runs else None

    # Handle HITL pauses
    while run_output and run_output.is_paused:
        handle_confirmation_hitl(run_output)

        print("\n[INFO] Continuing workflow with streaming...\n")

        # Continue with streaming
        continue_stream = workflow.continue_run(
            run_output, stream=True, stream_events=True
        )

        # Process continuation events
        process_event_stream(continue_stream)

        # Get updated run output
        session = workflow.get_session()
        run_output = session.runs[-1] if session and session.runs else None

    print("\n" + "=" * 60)
    print("Workflow finished!")
    print("=" * 60)
    if run_output:
        print(f"Status: {run_output.status}")
        print(f"Content: {run_output.content}")

        # Show step results
        if run_output.step_results:
            print("\nStep Results:")
            for result in run_output.step_results:
                status = "SUCCESS" if result.success else "SKIPPED"
                content = str(result.content)[:60] if result.content else "No content"
                print(f"  [{result.step_name}] {status}: {content}...")


if __name__ == "__main__":
    main()
