"""
Post-Execution Review — Approve / Reject / Cancel

Demonstrates the LangGraph-style HITL pattern using Agno's `requires_review`:

    START -> agent_a -> [PAUSE for review] -+- approve -> agent_b -> END
                                            +- reject  -> agent_a (retry)
                                            +- cancel  -> END

How it works:
    1. agent_a executes and produces output.
    2. The workflow pauses AFTER execution (not before) so the human can
       review the actual output.
    3. The human calls confirm() to approve, reject() to retry the step,
       or cancel() to cancel the entire workflow.
    4. On reject, the same step re-executes and pauses again for review.

Run:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/router/05_approve_reject_cancel.py
"""

from agno.db.sqlite import SqliteDb
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def draft_proposal(step_input: StepInput) -> StepOutput:
    """Agent A: generates a proposal draft."""
    return StepOutput(
        content="[Draft] Project proposal covering scope, timeline, and budget."
    )


def finalize_proposal(step_input: StepInput) -> StepOutput:
    """Agent B: finalizes the approved proposal."""
    draft = step_input.previous_step_content or ""
    return StepOutput(
        content=f"Proposal finalized and sent.\n\nApproved draft:\n{draft}"
    )


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="review_workflow",
    db=SqliteDb(db_file="tmp/review_workflow.db"),
    steps=[
        Step(
            name="agent_a",
            executor=draft_proposal,
            # Post-execution review: step runs first, then pauses for human review
            requires_review=True,
            review_message="Review Agent A's draft. Approve, reject, or cancel?",
            on_reject=OnReject.retry,  # reject = re-run the step
            review_max_retries=3,
        ),
        Step(
            name="agent_b",
            executor=finalize_proposal,
        ),
    ],
)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Post-Execution Review HITL Workflow")
    print("=" * 60)

    run_output = workflow.run("Create a project proposal")

    while run_output.is_paused:
        for req in run_output.steps_requiring_review:
            print(f"\nStep '{req.step_name}' produced:")
            print(f"  {req.step_output_content}")
            print(f"\n{req.review_message}")
            if req.review_retry_count > 0:
                print(f"  (attempt {req.review_retry_count}/{req.review_max_retries})")

            choice = input("\nYour choice (approve/reject/cancel): ").strip().lower()
            if choice == "approve":
                req.confirm()
            elif choice == "reject":
                req.reject()
            else:
                req.cancel()

        run_output = workflow.continue_run(run_output)

    print("\n" + "=" * 60)
    print(f"Status: {run_output.status}")
    print("=" * 60)
    if run_output.content:
        print(run_output.content)
