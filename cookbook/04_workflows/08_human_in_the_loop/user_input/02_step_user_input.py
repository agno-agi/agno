"""
Step-Level User Input HITL Example

This example demonstrates how to pause a workflow to collect user input
using Step parameters directly (without the @pause decorator).

This approach is useful when:
- Using agent-based steps that need user parameters
- You want to configure HITL at the Step level rather than on a function
- You need to override or add HITL to existing functions/agents

Use case: Collecting user preferences before an agent generates content.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
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


# Step 2: Content generator agent (HITL configured on Step, not function)
# Note: User input from HITL is automatically appended to the message as "User preferences:"
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
    name="content_generation_workflow",
    db=SqliteDb(db_file="tmp/workflow_step_user_input.db"),
    steps=[
        Step(name="gather_context", executor=gather_context),
        # HITL configured directly on the Step using agent
        Step(
            name="generate_content",
            agent=content_agent,
            requires_user_input=True,
            user_input_message="Please provide your content preferences:",
            user_input_schema=[
                UserInputField(
                    name="tone",
                    field_type="str",
                    description="Tone of the content: 'formal', 'casual', or 'technical'",
                    required=True,
                ),
                UserInputField(
                    name="length",
                    field_type="str",
                    description="Content length: 'short' (1 para), 'medium' (3 para), or 'long' (5+ para)",
                    required=True,
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


# Alternative: Using executor function with Step-level HITL
def process_data(step_input: StepInput) -> StepOutput:
    """Process data with user-specified options."""
    user_input = (
        step_input.additional_data.get("user_input", {})
        if step_input.additional_data
        else {}
    )

    format_type = user_input.get("format", "json")
    include_metadata = user_input.get("include_metadata", False)

    return StepOutput(
        content=f"Data processed with format: {format_type}, metadata: {include_metadata}"
    )


workflow_with_executor = Workflow(
    name="data_processing_workflow",
    db=SqliteDb(db_file="tmp/workflow_step_executor_input.db"),
    steps=[
        Step(name="gather_context", executor=gather_context),
        # HITL on Step with a plain executor function
        Step(
            name="process_data",
            executor=process_data,
            requires_user_input=True,
            user_input_message="Configure data processing:",
            user_input_schema=[
                UserInputField(
                    name="format",
                    field_type="str",
                    description="Output format: 'json', 'csv', or 'xml'",
                    required=True,
                ),
                UserInputField(
                    name="include_metadata",
                    field_type="bool",
                    description="Include metadata in output?",
                    required=False,
                ),
            ],
        ),
        Step(name="format_output", executor=format_output),
    ],
)


if __name__ == "__main__":
    print("=" * 60)
    print("Step-Level User Input HITL Example")
    print("=" * 60)
    print("\nThis example uses Step parameters for HITL configuration.")
    print("No @pause decorator needed - configure directly on Step.\n")

    # Run the agent-based workflow
    run_output = workflow.run("Python async programming")

    # Handle HITL pauses
    while run_output.is_paused:
        for requirement in run_output.steps_requiring_user_input:
            print(f"\n[HITL] Step '{requirement.step_name}' requires user input")
            print(f"[HITL] {requirement.user_input_message}")

            # Display schema and collect input
            if requirement.user_input_schema:
                print("\nFields (* = required):")
                user_values = {}
                for field in requirement.user_input_schema:
                    required_marker = "*" if field.required else ""
                    field_desc = f" - {field.description}" if field.description else ""
                    prompt = f"  {field.name}{required_marker} ({field.field_type}){field_desc}: "

                    value = input(prompt).strip()

                    # Convert to appropriate type
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

                # Set the user input
                requirement.set_user_input(**user_values)
                print("\n[HITL] Preferences received - continuing workflow...")

        # Check for confirmation requirements (if any)
        for requirement in run_output.steps_requiring_confirmation:
            print(f"\n[HITL] Step '{requirement.step_name}' requires confirmation")
            print(f"[HITL] {requirement.confirmation_message}")

            confirm = input("\nContinue? (yes/no): ").strip().lower()
            if confirm in ("yes", "y"):
                requirement.confirm()
            else:
                requirement.reject()

        # Continue the workflow
        run_output = workflow.continue_run(run_output)

    print("\n" + "=" * 60)
    print(f"Status: {run_output.status}")
    print("=" * 60)
    print(run_output.content)
