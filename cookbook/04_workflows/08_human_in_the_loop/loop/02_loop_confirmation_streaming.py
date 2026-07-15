"""
Loop with User Confirmation HITL Example (Streaming)

This example demonstrates start confirmation for Loop components with streaming.

When `requires_confirmation=True`:
- Pauses before the first iteration
- User confirms -> execute loop
- User rejects -> skip loop entirely

Streaming mode emits events like:
- WorkflowStartedEvent
- StepPausedEvent (when loop requires confirmation)
- StepStartedEvent / StepCompletedEvent
- WorkflowCompletedEvent

Key difference from non-streaming:
- Get WorkflowRunOutput from session after streaming completes
"""

from agno.db.sqlite import SqliteDb
from agno.run.workflow import (
    StepCompletedEvent,
    StepPausedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowStartedEvent,
)
from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ============================================================
# Step functions
# ============================================================
def prepare_data(step_input: StepInput) -> StepOutput:
    """Prepare data for processing."""
    return StepOutput(
        content="Data prepared for iterative processing.\n"
        "Ready to begin refinement loop."
    )


def refine_analysis(step_input: StepInput) -> StepOutput:
    """Perform one iteration of analysis refinement."""
    iteration = getattr(step_input, "_iteration_count", 1)
    return StepOutput(
        content=f"Iteration {iteration} complete:\n"
        f"- Quality score: {70 + iteration * 10}%\n"
        f"- Improvements made: {iteration * 3}\n"
        "- Further refinement possible"
    )


def finalize_results(step_input: StepInput) -> StepOutput:
    """Finalize the results."""
    previous_content = step_input.previous_step_content or "No iterations"
    return StepOutput(
        content=f"=== FINAL RESULTS ===\n\n{previous_content}\n\nProcessing complete."
    )


# Define the steps
prepare_step = Step(name="prepare_data", executor=prepare_data)

# Loop with start confirmation - user must confirm to start the loop
refinement_loop = Loop(
    name="refinement_loop",
    steps=[Step(name="refine_analysis", executor=refine_analysis)],
    max_iterations=5,
    requires_confirmation=True,
    confirmation_message="Start the refinement loop? This may take several iterations.",
)

finalize_step = Step(name="finalize_results", executor=finalize_results)

# Create workflow with database for HITL persistence
workflow = Workflow(
    name="loop_start_confirmation_streaming_demo",
    steps=[prepare_step, refinement_loop, finalize_step],
    db=SqliteDb(db_file="tmp/loop_hitl_streaming.db"),
)


def process_event_stream(event_stream):
    """Process events from a workflow stream."""
    for event in event_stream:
        if isinstance(event, WorkflowStartedEvent):
            print("\n[EVENT] Workflow started")

        elif isinstance(event, StepStartedEvent):
            print(f"[EVENT] Step started: {event.step_name}")

        elif isinstance(event, StepPausedEvent):
            print(f"\n[EVENT] Step paused: {event.step_name}")
            print(f"  Requires confirmation: {event.requires_confirmation}")
            if event.confirmation_message:
                print(f"  Message: {event.confirmation_message}")

        elif isinstance(event, StepCompletedEvent):
            print(f"[EVENT] Step completed: {event.step_name}")

        elif isinstance(event, WorkflowCompletedEvent):
            print("\n[EVENT] Workflow completed")


def handle_confirmation_hitl(run_output):
    """Handle confirmation HITL requirements."""
    for requirement in run_output.steps_requiring_confirmation:
        print(f"\n[DECISION POINT] {requirement.step_name}")
        print(f"[HITL] {requirement.confirmation_message}")

        user_choice = input("\nStart the loop? (yes/no): ").strip().lower()
        if user_choice in ("yes", "y"):
            requirement.confirm()
            print("[HITL] Confirmed - starting loop")
        else:
            requirement.reject()
            print("[HITL] Rejected - skipping loop")


def main():
    print("=" * 60)
    print("Loop with Start Confirmation HITL Example (Streaming)")
    print("=" * 60)

    # Initial run with streaming
    event_stream = workflow.run(
        "Process quarterly data", stream=True, stream_events=True
    )

    # Process initial events
    process_event_stream(event_stream)

    # Get run output from session (key difference for streaming!)
    session = workflow.get_session()
    run_output = session.runs[-1] if session and session.runs else None

    # Handle HITL pauses with streaming continuation
    while run_output and run_output.is_paused:
        handle_confirmation_hitl(run_output)

        print("\n[INFO] Continuing workflow with streaming...\n")

        # Continue with streaming
        continue_stream = workflow.continue_run(
            run_output, stream=True, stream_events=True
        )

        # Process continuation events
        process_event_stream(continue_stream)

        # Get updated run output from session
        session = workflow.get_session()
        run_output = session.runs[-1] if session and session.runs else None

    print("\n" + "=" * 60)
    if run_output:
        print(f"Status: {run_output.status}")
        print("=" * 60)
        print(run_output.content)
    else:
        print("No output received")
        print("=" * 60)


if __name__ == "__main__":
    main()
