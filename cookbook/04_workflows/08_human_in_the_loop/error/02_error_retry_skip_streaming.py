"""
Error HITL: Retry or Skip Failed Steps (Streaming)

This example demonstrates how to use HITL when a step encounters an error,
with streaming execution for real-time event updates.

Key differences from non-streaming:
1. workflow.run(..., stream=True) returns an Iterator of events
2. stream_events=True is required to receive StepStartedEvent/StepCompletedEvent
3. Events include StepErrorEvent when errors occur
4. Get WorkflowRunOutput from session after streaming
5. Use workflow.continue_run(..., stream=True, stream_events=True) for consistent streaming

Use Case:
- API calls that may fail due to rate limits or network issues
- Operations that may timeout but could succeed on retry
- Steps where intermittent failures are expected
- Real-time progress updates during workflow execution
"""

import random

from agno.db.sqlite import SqliteDb
from agno.run.workflow import (
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowStartedEvent,
)
from agno.workflow import OnError
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# A function that randomly fails to simulate an unreliable operation
def unreliable_api_call(step_input: StepInput) -> StepOutput:
    """Simulates an API call that may fail randomly."""
    if random.random() < 0.99:  # 99% chance of failure
        raise Exception("API call failed: Connection timeout")

    return StepOutput(
        content="API call succeeded! Data fetched successfully.",
        success=True,
    )


def process_data(step_input: StepInput) -> StepOutput:
    """Process the data from the previous step."""
    previous_content = step_input.previous_step_content or "No data"
    return StepOutput(
        content=f"Processed: {previous_content}",
        success=True,
    )


def save_results(step_input: StepInput) -> StepOutput:
    """Save the processed results."""
    previous_content = step_input.previous_step_content or "No data"
    return StepOutput(
        content=f"Saved: {previous_content}",
        success=True,
    )


# Create the workflow
workflow = Workflow(
    name="error_hitl_streaming_workflow",
    db=SqliteDb(db_file="tmp/error_hitl_streaming.db"),
    steps=[
        Step(
            name="fetch_data",
            executor=unreliable_api_call,
            on_error=OnError.pause,  # Pause on error and let user decide
        ),
        Step(
            name="process_data",
            executor=process_data,
        ),
        Step(
            name="save_results",
            executor=save_results,
        ),
    ],
)


def handle_error_hitl(run_output):
    """Handle error HITL requirements."""
    if run_output.steps_with_errors:
        for error_req in run_output.steps_with_errors:
            print("\n" + "-" * 40)
            print(f"Step '{error_req.step_name}' FAILED")
            print(f"Error Type: {error_req.error_type}")
            print(f"Error Message: {error_req.error_message}")
            print(f"Retry Count: {error_req.retry_count}")
            print("-" * 40)

            user_choice = (
                input("\nWhat would you like to do? (retry/skip): ").strip().lower()
            )

            if user_choice == "retry":
                error_req.retry()
                print("Retrying the step...")
            else:
                error_req.skip()
                print("Skipping the step and continuing...")


def main():
    print("=" * 60)
    print("Error HITL: Retry or Skip Failed Steps (Streaming)")
    print("=" * 60)
    print("The 'fetch_data' step has a 70% chance of failing.")
    print("When it fails, you can choose to retry or skip.")
    print("\nStarting workflow with streaming...\n")

    # Run with streaming - returns an iterator of events
    # stream=True enables streaming output, stream_events=True enables step events
    event_stream = workflow.run(
        "Fetch and process data", stream=True, stream_events=True
    )

    for event in event_stream:
        if isinstance(event, WorkflowStartedEvent):
            print(f"[EVENT] Workflow started: {event.workflow_name}")

        elif isinstance(event, StepStartedEvent):
            print(f"[EVENT] Step started: {event.step_name}")

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

    # Get run output from session
    session = workflow.get_session()
    run_output = session.runs[-1] if session and session.runs else None

    # Handle HITL pauses
    while run_output and run_output.is_paused:
        handle_error_hitl(run_output)

        print("\n[INFO] Continuing workflow with streaming...\n")

        # Continue with streaming
        continue_stream = workflow.continue_run(
            run_output, stream=True, stream_events=True
        )

        for event in continue_stream:
            if isinstance(event, StepStartedEvent):
                print(f"[EVENT] Step started: {event.step_name}")

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
                status = "SUCCESS" if result.success else "FAILED/SKIPPED"
                content = result.content[:60] if result.content else "No content"
                print(f"  [{result.step_name}] {status}: {content}...")


if __name__ == "__main__":
    main()
