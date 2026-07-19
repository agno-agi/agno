"""
Condition on_error Handling
===========================

Demonstrates how to control error handling within Condition steps using the
`on_error` parameter. When a sub-step inside a Condition fails, you can choose
to skip (default), fail the entire workflow, or pause for HITL resolution.

Three modes:
- OnError.skip  : Log the error, stop remaining sub-steps in the condition,
                   and let the workflow continue to the next step.
- OnError.fail  : Re-raise the exception so the workflow fails immediately.
- OnError.pause : Pause the workflow and create an ErrorRequirement that the
                   user can resolve by choosing to retry or skip.
"""

from agno.db.sqlite import SqliteDb
from agno.workflow import Condition, OnError
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ---------------------------------------------------------------------------
# Helper steps
# ---------------------------------------------------------------------------
def validate_data(step_input: StepInput) -> StepOutput:
    """Validates incoming data. Always fails to demonstrate error handling."""
    raise ValueError("Data validation failed: missing required fields")


def enrich_data(step_input: StepInput) -> StepOutput:
    """Enriches data with additional information."""
    previous = step_input.previous_step_content or "raw data"
    return StepOutput(content=f"Enriched: {previous}", success=True)


def save_data(step_input: StepInput) -> StepOutput:
    """Saves the final result."""
    previous = step_input.previous_step_content or "no data"
    return StepOutput(content=f"Saved: {previous}", success=True)


def should_validate(step_input: StepInput) -> bool:
    """Evaluator that checks if validation is needed."""
    text = step_input.input or ""
    return "validate" in text.lower()


# ---------------------------------------------------------------------------
# Example 1: on_error="skip" (default) -- errors are logged, workflow continues
# ---------------------------------------------------------------------------
def run_skip_example():
    print("=" * 60)
    print("Example 1: on_error='skip' (default)")
    print("=" * 60)

    workflow = Workflow(
        name="skip_error_workflow",
        db=SqliteDb(db_file="tmp/condition_on_error.db"),
        steps=[
            Condition(
                name="validate_if_needed",
                evaluator=should_validate,
                steps=[validate_data, enrich_data],
                on_error=OnError.skip,
            ),
            Step(name="save", executor=save_data),
        ],
    )

    result = workflow.run("Please validate and save")
    print(f"Status: {result.status}")
    print(f"Content: {result.content}")
    if result.step_results:
        for sr in result.step_results:
            print(
                f"  [{sr.step_name}] success={sr.success}: {sr.content[:80] if sr.content else ''}"
            )
    print()


# ---------------------------------------------------------------------------
# Example 2: on_error="fail" -- exception propagates, workflow stops
# ---------------------------------------------------------------------------
def run_fail_example():
    print("=" * 60)
    print("Example 2: on_error='fail'")
    print("=" * 60)

    workflow = Workflow(
        name="fail_error_workflow",
        db=SqliteDb(db_file="tmp/condition_on_error.db"),
        steps=[
            Condition(
                name="validate_if_needed",
                evaluator=should_validate,
                steps=[validate_data, enrich_data],
                on_error=OnError.fail,
            ),
            Step(name="save", executor=save_data),
        ],
    )

    try:
        workflow.run("Please validate and save")
    except ValueError as e:
        print(f"Workflow failed as expected: {e}")
    print()


# ---------------------------------------------------------------------------
# Example 3: on_error="pause" -- workflow pauses for HITL resolution
# ---------------------------------------------------------------------------
def run_pause_example():
    print("=" * 60)
    print("Example 3: on_error='pause' (HITL)")
    print("=" * 60)

    workflow = Workflow(
        name="pause_error_workflow",
        db=SqliteDb(db_file="tmp/condition_on_error.db"),
        steps=[
            Condition(
                name="validate_if_needed",
                evaluator=should_validate,
                steps=[validate_data, enrich_data],
                on_error=OnError.pause,
            ),
            Step(name="save", executor=save_data),
        ],
    )

    run_output = workflow.run("Please validate and save")

    while run_output.is_paused:
        if run_output.steps_with_errors:
            for error_req in run_output.steps_with_errors:
                print(f"Step '{error_req.step_name}' failed: {error_req.error_message}")
                print(f"Error type: {error_req.error_type}")

                choice = input("Retry or skip? (retry/skip): ").strip().lower()
                if choice == "retry":
                    error_req.retry()
                    print("Retrying...")
                else:
                    error_req.skip()
                    print("Skipping...")

        run_output = workflow.continue_run(run_output)

    print(f"Status: {run_output.status}")
    print(f"Content: {run_output.content}")
    if run_output.step_results:
        for sr in run_output.step_results:
            print(
                f"  [{sr.step_name}] success={sr.success}: {sr.content[:80] if sr.content else ''}"
            )
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_skip_example()
    run_fail_example()
    run_pause_example()
