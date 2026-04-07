"""
Post-Execution Review — Approve / Reject / Cancel (Streaming)

Streaming variant of 05_approve_reject_cancel.py.

    START -> agent_a -> [PAUSE for review] -+- approve -> agent_b -> END
                                            +- reject  -> agent_a (retry)
                                            +- cancel  -> END

Key difference from non-streaming:
    - workflow.run(stream=True) yields events; the WorkflowRunOutput is
      retrieved from the session after the stream is consumed.

Run:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/router/06_approve_reject_cancel_streaming.py
"""

from agno.db.sqlite import SqliteDb
from agno.run.workflow import (
    StepCompletedEvent,
    StepPausedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowStartedEvent,
)
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
    name="review_workflow_streaming",
    db=SqliteDb(db_file="tmp/review_workflow_streaming.db"),
    steps=[
        Step(
            name="agent_a",
            executor=draft_proposal,
            requires_review=True,
            review_message="Review Agent A's draft. Approve, reject, or cancel?",
            on_reject=OnReject.retry,
            review_max_retries=3,
        ),
        Step(
            name="agent_b",
            executor=finalize_proposal,
        ),
    ],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def consume_stream(event_stream):
    """Consume and print events from a workflow stream."""
    for event in event_stream:
        if isinstance(event, WorkflowStartedEvent):
            print("[EVENT] Workflow started")
        elif isinstance(event, StepStartedEvent):
            print(f"[EVENT] Step started: {event.step_name}")
        elif isinstance(event, StepPausedEvent):
            print(f"[EVENT] Step paused: {event.step_name}")
        elif isinstance(event, StepCompletedEvent):
            print(f"[EVENT] Step completed: {event.step_name}")
        elif isinstance(event, WorkflowCompletedEvent):
            print("[EVENT] Workflow completed")


def get_run_output():
    """Retrieve the latest run output from the session."""
    session = workflow.get_session()
    if session and session.runs:
        return session.runs[-1]
    return None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Post-Execution Review HITL Workflow (Streaming)")
    print("=" * 60)

    # Initial run with streaming
    consume_stream(
        workflow.run("Create a project proposal", stream=True, stream_events=True)
    )
    run_output = get_run_output()

    while run_output and run_output.is_paused:
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

        # Continue with streaming
        consume_stream(
            workflow.continue_run(run_output, stream=True, stream_events=True)
        )
        run_output = get_run_output()

    print("\n" + "=" * 60)
    if run_output:
        print(f"Status: {run_output.status}")
        print("=" * 60)
        if run_output.content:
            print(run_output.content)
    else:
        print("No output received")
        print("=" * 60)
