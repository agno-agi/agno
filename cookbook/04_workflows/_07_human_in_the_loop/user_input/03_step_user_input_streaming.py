"""
Step-Level User Input HITL Example (Streaming)

This example demonstrates how to handle HITL with streaming workflows.

Key differences from non-streaming:
1. workflow.run(..., stream=True) returns an Iterator of events
2. stream_events=True is required to receive StepStartedEvent/StepCompletedEvent
3. Look for StepPausedEvent to detect HITL pauses
4. Events are processed as they stream in
5. Use workflow.continue_run(..., stream=True, stream_events=True) to continue with streaming

This is useful for:
- Real-time progress updates
- Large workflows where you want incremental feedback
- UI integrations that show step-by-step progress
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.workflow import (
    StepCompletedEvent,
    StepPausedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
    WorkflowStartedEvent,
)
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput, UserInputField
from agno.workflow.workflow import Workflow


# Step 1: Gather context (no HITL)
def gather_context(step_input: StepInput) -> StepOutput:
    """Gather initial context from the input."""
    topic = step_input.input or "general topic"
    return StepOutput(
        content=f"Context gathered for: '{topic}'\n"
        "Ready to generate content based on user preferences."
    )


# Step 2: Content generator agent (HITL configured on Step)
content_agent = Agent(
    name="Content Generator",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a content generator.",
        "Generate content based on the topic and user preferences provided.",
        "The user preferences will be provided in the message - use them to guide your output.",
        "Respect the tone, length, and format specified by the user.",
        "Keep the output focused and professional.",
    ],
)


# Step 3: Format output (no HITL)
def format_output(step_input: StepInput) -> StepOutput:
    """Format the final output."""
    content = step_input.previous_step_content or "No content generated"
    return StepOutput(content=f"=== GENERATED CONTENT ===\n\n{content}\n\n=== END ===")


# Define workflow with Step-level HITL configuration
workflow = Workflow(
    name="content_generation_workflow_stream",
    db=SqliteDb(db_file="tmp/workflow_step_user_input_stream.db"),
    steps=[
        Step(name="gather_context", executor=gather_context),
        Step(
            name="generate_content",
            agent=content_agent,
            requires_user_input=True,
            user_input_message="Please provide your content preferences:",
            user_input_schema=[
                UserInputField(
                    name="tone",
                    field_type="str",
                    description="Tone of the content",
                    required=True,
                    # Validation: only these values are allowed
                    allowed_values=["formal", "casual", "technical"],
                ),
                UserInputField(
                    name="length",
                    field_type="str",
                    description="Content length",
                    required=True,
                    allowed_values=["short", "medium", "long"],
                ),
                UserInputField(
                    name="include_examples",
                    field_type="bool",
                    description="Include practical examples?",
                    required=False,
                ),
            ],
        ),
        Step(name="format_output", executor=format_output),
    ],
)


def handle_hitl_pause(run_output: WorkflowRunOutput) -> None:
    """Handle HITL requirements from the paused workflow."""
    # Handle user input requirements
    for requirement in run_output.steps_requiring_user_input:
        print(f"\n[HITL] Step '{requirement.step_name}' requires user input")
        print(f"[HITL] {requirement.user_input_message}")

        if requirement.user_input_schema:
            print("\nFields (* = required):")
            user_values = {}
            for field in requirement.user_input_schema:
                required_marker = "*" if field.required else ""
                field_desc = f" - {field.description}" if field.description else ""
                # Show allowed values if specified
                allowed_hint = (
                    f" [{', '.join(str(v) for v in field.allowed_values)}]"
                    if field.allowed_values
                    else ""
                )
                prompt = f"  {field.name}{required_marker} ({field.field_type}){allowed_hint}{field_desc}: "

                value = input(prompt).strip()

                if value:
                    if field.field_type == "int":
                        user_values[field.name] = int(value)
                    elif field.field_type == "float":
                        user_values[field.name] = float(value)
                    elif field.field_type == "bool":
                        user_values[field.name] = value.lower() in (
                            "true",
                            "yes",
                            "1",
                            "y",
                        )
                    else:
                        user_values[field.name] = value

            # set_user_input validates by default; catch validation errors
            try:
                requirement.set_user_input(**user_values)
                print("\n[HITL] Preferences received - continuing workflow...")
            except ValueError as e:
                print(f"\n[HITL] Validation error: {e}")
                print("[HITL] Please provide valid input.")
                # In a real app, you'd loop and re-prompt
                raise

    # Handle confirmation requirements
    for requirement in run_output.steps_requiring_confirmation:
        print(f"\n[HITL] Step '{requirement.step_name}' requires confirmation")
        print(f"[HITL] {requirement.confirmation_message}")

        confirm = input("\nContinue? (yes/no): ").strip().lower()
        if confirm in ("yes", "y"):
            requirement.confirm()
        else:
            requirement.reject()


def run_workflow_streaming(input_text: str) -> WorkflowRunOutput:
    """Run workflow with streaming and handle HITL pauses."""
    print("=" * 60)
    print("Step-Level User Input HITL Example (Streaming)")
    print("=" * 60)
    print("\nStarting workflow with streaming...\n")

    # Track the final run output
    run_output: WorkflowRunOutput | None = None

    # Run with streaming - returns an iterator of events
    # stream=True enables streaming output, stream_events=True enables step events
    event_stream = workflow.run(input_text, stream=True, stream_events=True)

    for event in event_stream:
        # Check event type and handle accordingly
        if isinstance(event, WorkflowStartedEvent):
            print(f"[EVENT] Workflow started: {event.workflow_name}")

        elif isinstance(event, StepStartedEvent):
            print(f"[EVENT] Step started: {event.step_name}")

        elif isinstance(event, StepCompletedEvent):
            print(f"[EVENT] Step completed: {event.step_name}")
            if event.content:
                # Show preview of content (truncated)
                preview = (
                    str(event.content)[:100] + "..."
                    if len(str(event.content)) > 100
                    else str(event.content)
                )
                print(f"        Content: {preview}")

        elif isinstance(event, StepPausedEvent):
            # HITL pause detected!
            print(f"\n[EVENT] Step PAUSED: {event.step_name}")
            if event.requires_user_input:
                print("        Reason: User input required")
                print(f"        Message: {event.user_input_message}")
            elif event.requires_confirmation:
                print("        Reason: Confirmation required")
                print(f"        Message: {event.confirmation_message}")

        elif isinstance(event, WorkflowCompletedEvent):
            print("\n[EVENT] Workflow completed!")
            print(
                f"        Final content length: {len(str(event.content)) if event.content else 0} chars"
            )

        # Check if the event contains the workflow run output
        # (some events have a workflow_run_output attribute)
        if hasattr(event, "workflow_run_output") and event.workflow_run_output:
            run_output = event.workflow_run_output

    # After streaming, we need to get the current run state
    # The last event in a paused workflow should give us the state
    # If run_output is still None, get it from session
    if run_output is None:
        # Get the latest run from the session
        session = workflow.get_session()
        if session and session.runs:
            run_output = session.runs[-1]

    # If workflow is paused, handle HITL and continue
    while run_output and run_output.is_paused:
        handle_hitl_pause(run_output)

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
                        str(event.content)[:100] + "..."
                        if len(str(event.content)) > 100
                        else str(event.content)
                    )
                    print(f"        Content: {preview}")

            elif isinstance(event, StepPausedEvent):
                print(f"\n[EVENT] Step PAUSED: {event.step_name}")

            elif isinstance(event, WorkflowCompletedEvent):
                print("\n[EVENT] Workflow completed!")

            if hasattr(event, "workflow_run_output") and event.workflow_run_output:
                run_output = event.workflow_run_output

        # Get updated run output from session
        session = workflow.get_session()
        if session and session.runs:
            run_output = session.runs[-1]

    return run_output  # type: ignore


if __name__ == "__main__":
    final_output = run_workflow_streaming("Python async programming")

    print("\n" + "=" * 60)
    print(f"Final Status: {final_output.status}")
    print("=" * 60)
    print(final_output.content)
