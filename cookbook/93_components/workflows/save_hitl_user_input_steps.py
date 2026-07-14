"""
Save HITL User Input Workflow Steps
=====================================

Demonstrates creating a workflow that pauses to collect structured user
input, saving it to the database, and loading it back. The user_input_schema
(field names, types, descriptions) round-trips through to_dict / from_dict.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.registry import Registry
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput, UserInputField
from agno.workflow.workflow import Workflow, get_workflow_by_id

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agents and Functions
# ---------------------------------------------------------------------------
content_agent = Agent(
    id="hitl-input-content-gen",
    name="Content Generator",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "Generate content based on the topic and user preferences provided.",
        "Respect the tone, length, and format specified by the user.",
    ],
)


def format_output(step_input: StepInput) -> StepOutput:
    """Format the final output."""
    content = step_input.previous_step_content or "No content generated"
    return StepOutput(content=f"=== GENERATED CONTENT ===\n\n{content}\n\n=== END ===")


# ---------------------------------------------------------------------------
# Registry (required to resolve agents when loading from DB)
# ---------------------------------------------------------------------------
registry = Registry(
    name="HITL User Input Registry",
    agents=[content_agent],
    functions=[format_output],
    dbs=[db],
)

# ---------------------------------------------------------------------------
# Create Workflow with HITL User Input
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="HITL User Input Workflow",
    description="Workflow that collects user preferences before generating content",
    steps=[
        Step(
            name="GenerateContent",
            description="Generate content with user-specified preferences",
            agent=content_agent,
            requires_user_input=True,
            user_input_message="Please provide your content preferences:",
            user_input_schema=[
                UserInputField(
                    name="tone",
                    field_type="str",
                    description="Tone: 'formal', 'casual', or 'technical'",
                    required=True,
                ),
                UserInputField(
                    name="length",
                    field_type="str",
                    description="Length: 'short', 'medium', or 'long'",
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
        Step(
            name="FormatOutput",
            description="Format the generated content",
            executor=format_output,
        ),
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Save, Load, and Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Save workflow to database
    print("Saving workflow with HITL user input config...")
    version = workflow.save(db=db)
    print(f"Saved as version {version}")

    # Load workflow back from database
    print("\nLoading workflow...")
    loaded_workflow = get_workflow_by_id(
        db=db,
        id="hitl-user-input-workflow",
        registry=registry,
    )

    if loaded_workflow is None:
        print("Workflow not found")
        exit(1)

    print("Workflow loaded successfully!")

    # Verify HITL user input config survived the round-trip
    if loaded_workflow.steps:
        for step in loaded_workflow.steps:
            if hasattr(step, "requires_user_input") and step.requires_user_input:
                print(f"\n  Step '{step.name}' has HITL user input config:")
                print(f"    requires_user_input: {step.requires_user_input}")
                print(f"    user_input_message: {step.user_input_message}")
                print(f"    user_input_schema: {step.user_input_schema}")

    # Run the loaded workflow
    print("\nRunning loaded workflow...")
    run_output = loaded_workflow.run("Python async programming")

    # Handle HITL pauses
    while run_output.is_paused:
        for requirement in run_output.steps_requiring_user_input:
            print(f"\n[HITL] Step '{requirement.step_name}' requires user input")
            print(f"[HITL] {requirement.user_input_message}")

            if requirement.user_input_schema:
                print("\nFields (* = required):")
                user_values = {}
                for field in requirement.user_input_schema:
                    marker = "*" if field.required else ""
                    desc = f" - {field.description}" if field.description else ""
                    prompt = f"  {field.name}{marker} ({field.field_type}){desc}: "

                    value = input(prompt).strip()
                    if value:
                        if field.field_type == "bool":
                            user_values[field.name] = value.lower() in (
                                "true",
                                "yes",
                                "1",
                                "y",
                            )
                        elif field.field_type == "int":
                            user_values[field.name] = int(value)
                        elif field.field_type == "float":
                            user_values[field.name] = float(value)
                        else:
                            user_values[field.name] = value

                requirement.set_user_input(**user_values)
                print("\n[HITL] Preferences received")

        run_output = loaded_workflow.continue_run(run_output)

    print(f"\nStatus: {run_output.status}")
    print(run_output.content)
