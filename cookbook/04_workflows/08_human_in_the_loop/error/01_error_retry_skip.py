"""
Error HITL: Retry or Skip Failed Steps

This example demonstrates how to use HITL when a step encounters an error.
When a step with `on_error="pause"` fails, the workflow pauses and lets the user
decide to either retry the step or skip it and continue with the next step.

Use Case:
- API calls that may fail due to rate limits or network issues
- Operations that may timeout but could succeed on retry
- Steps where intermittent failures are expected
"""

import random

from agno.db.sqlite import SqliteDb
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
    name="error_hitl_workflow",
    db=SqliteDb(db_file="tmp/error_hitl.db"),
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


def main():
    print("=" * 60)
    print("Error HITL: Retry or Skip Failed Steps")
    print("=" * 60)
    print("The 'fetch_data' step has a 70% chance of failing.")
    print("When it fails, you can choose to retry or skip.")
    print()

    run_output = workflow.run("Fetch and process data")

    while run_output.is_paused:
        # Check for error requirements
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

        # Continue the workflow
        run_output = workflow.continue_run(run_output)

    print("\n" + "=" * 60)
    print("Workflow completed!")
    print("=" * 60)
    print(f"Status: {run_output.status}")
    print(f"Content: {run_output.content}")

    # Show step results
    if run_output.step_results:
        print("\nStep Results:")
        for result in run_output.step_results:
            status = "SUCCESS" if result.success else "FAILED/SKIPPED"
            print(
                f"  [{result.step_name}] {status}: {result.content[:80] if result.content else 'No content'}..."
            )


if __name__ == "__main__":
    main()
