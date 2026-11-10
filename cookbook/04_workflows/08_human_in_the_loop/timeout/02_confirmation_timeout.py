"""
Confirmation Timeout Example

Demonstrates timeout with pre-execution confirmation (requires_confirmation)
using the HITL config class. The step pauses BEFORE execution and waits for
human approval. If no one responds within the timeout, the on_timeout action
fires automatically.

Three timeout behaviors:
  - on_timeout="approve": Auto-confirm and execute the step
  - on_timeout="skip": Skip the step, continue workflow
  - on_timeout="cancel": Cancel the entire workflow

Timeout is checked lazily at continue_run() time -- no background timer needed.
The timeout_at field on StepRequirement can be used by a UI for countdown display.

Run:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/timeout/02_confirmation_timeout.py
"""

import time

from agno.db.sqlite import SqliteDb
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnTimeout, StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def prepare_data(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Data prepared and ready for processing.")


def delete_old_records(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Deleted 1,247 records older than 90 days.")


def generate_report(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Report: {prev}")


# ---------------------------------------------------------------------------
# Workflow -- dangerous step with confirmation + timeout via HITL config
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="confirmation_timeout_demo",
    db=SqliteDb(db_file="tmp/confirmation_timeout.db"),
    steps=[
        Step(name="prepare", executor=prepare_data),
        Step(
            name="delete_records",
            executor=delete_old_records,
            human_review=HumanReview(
                # Pre-execution confirmation: pauses BEFORE the step runs
                requires_confirmation=True,
                confirmation_message="About to delete old records. Proceed?",
                on_reject=OnReject.skip,
                # Timeout: auto-skip if no human responds within 10 seconds
                timeout=10,
                on_timeout=OnTimeout.skip,
            ),
        ),
        Step(name="report", executor=generate_report),
    ],
)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Confirmation Timeout Example")
    print("=" * 60)

    run_output = workflow.run("Process quarterly data")

    if run_output.is_paused:
        for req in run_output.steps_requiring_confirmation:
            print(f"\nStep '{req.step_name}' requires confirmation:")
            print(f"  Message: {req.confirmation_message}")
            print(f"  Timeout at: {req.timeout_at}")
            print(f"  On timeout: {req.on_timeout}")

        # Option 1: Human responds in time
        # req.confirm()  # or req.reject()
        # run_output = workflow.continue_run(run_output)

        # Option 2: Simulate timeout -- wait past the deadline
        print("\nSimulating 11 second delay (timeout is 10 seconds)...")
        time.sleep(11)

        # continue_run checks timeout and auto-resolves
        run_output = workflow.continue_run(run_output)
        print("Auto-resolved by timeout (step was skipped).")

    print(f"\nStatus: {run_output.status}")
    print(f"Output: {run_output.content}")
