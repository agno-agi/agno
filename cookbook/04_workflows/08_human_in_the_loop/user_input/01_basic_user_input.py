"""
Basic User Input HITL Example

This example demonstrates how to pause a workflow to collect user input
before executing a step. The user input is then available to the step
via step_input.additional_data["user_input"].

Use case: Collecting parameters from the user before processing data.

Two ways to define user_input_schema:
1. List of UserInputField objects (recommended) - explicit and type-safe
2. List of dicts - simple but less explicit
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow.decorators import pause
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput, UserInputField
from agno.workflow.workflow import Workflow


# Step 1: Analyze data (no HITL)
def analyze_data(step_input: StepInput) -> StepOutput:
    """Analyze the data and provide summary."""
    user_query = step_input.input or "data"
    return StepOutput(
        content=f"Analysis complete: Found 1000 records matching '{user_query}'. "
        "Ready for processing with user-specified parameters."
    )


# Step 2: Process with user-provided parameters (HITL - user input)
# Using UserInputField for schema - explicit and type-safe
@pause(
    name="Process Data",
    requires_user_input=True,
    user_input_message="Please provide processing parameters:",
    user_input_schema=[
        UserInputField(
            name="threshold",
            field_type="float",
            description="Processing threshold (0.0 to 1.0)",
            required=True,
        ),
        UserInputField(
            name="mode",
            field_type="str",
            description="Processing mode: 'fast' or 'accurate'",
            required=True,
        ),
        UserInputField(
            name="batch_size",
            field_type="int",
            description="Number of records per batch",
            required=False,
        ),
    ],
)
def process_with_params(step_input: StepInput) -> StepOutput:
    """Process data with user-provided parameters."""
    # Get user input from additional_data
    user_input = (
        step_input.additional_data.get("user_input", {})
        if step_input.additional_data
        else {}
    )

    threshold = user_input.get("threshold", 0.5)
    mode = user_input.get("mode", "fast")
    batch_size = user_input.get("batch_size", 100)

    previous = step_input.previous_step_content or ""

    return StepOutput(
        content=f"Processing complete!\n"
        f"- Input: {previous}\n"
        f"- Threshold: {threshold}\n"
        f"- Mode: {mode}\n"
        f"- Batch size: {batch_size}\n"
        f"- Records processed: 1000"
    )


# Step 3: Generate report (no HITL)
writer_agent = Agent(
    name="Report Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a report writer.",
        "Given processing results, write a brief summary report.",
        "Keep it concise - 2-3 sentences.",
    ],
)


# Define steps
analyze_step = Step(name="analyze_data", executor=analyze_data)
process_step = Step(
    name="process_data", executor=process_with_params
)  # @pause auto-detected
report_step = Step(name="generate_report", agent=writer_agent)

# Create workflow
workflow = Workflow(
    name="data_processing_with_params",
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    steps=[analyze_step, process_step, report_step],
)

if __name__ == "__main__":
    print("Starting data processing workflow...")
    print("=" * 50)

    run_output = workflow.run("customer transactions from Q4")

    # Handle HITL pauses
    while run_output.is_paused:
        # Show paused step info
        print(
            f"\n[PAUSED] Workflow paused at step {run_output.paused_step_index}: '{run_output.paused_step_name}'"
        )

        # Check for user input requirements
        for requirement in run_output.steps_requiring_user_input:
            print(f"\n[HITL] Step '{requirement.step_name}' requires user input")
            print(f"[HITL] {requirement.user_input_message}")

            # Display schema and collect input
            if requirement.user_input_schema:
                print("\nRequired fields:")
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
                            )
                        else:
                            user_values[field.name] = value

                # Set the user input
                requirement.set_user_input(**user_values)
                print("\n[HITL] User input received - continuing workflow...")

        # Check for confirmation requirements
        for requirement in run_output.steps_requiring_confirmation:
            print(f"\n[HITL] Step '{requirement.step_name}' requires confirmation")
            print(f"[HITL] {requirement.confirmation_message}")

            user_input = input("\nContinue? (yes/no): ").strip().lower()
            if user_input in ("yes", "y"):
                requirement.confirm()
            else:
                requirement.reject()

        # Continue the workflow
        run_output = workflow.continue_run(run_output)

    print("\n" + "=" * 50)
    print(f"Status: {run_output.status}")
    print(f"Output:\n{run_output.content}")
