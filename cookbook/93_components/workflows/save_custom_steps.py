"""
Save Custom Executor Workflow Steps
===================================

Demonstrates creating a workflow with custom executor steps, saving it to the
database, and loading it back with a Registry.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.registry import Registry
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow, get_workflow_by_id

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
# Agents
content_agent = Agent(
    name="Content Creator",
    instructions="Create well-structured content from input data",
)


# ---------------------------------------------------------------------------
# Create Registry Components
# ---------------------------------------------------------------------------
# Custom executor function (will be serialized by name and restored via registry)
def transform_content(step_input: StepInput) -> StepOutput:
    """Custom executor function that transforms content."""
    previous_content = step_input.previous_step_content or ""
    transformed = f"[TRANSFORMED] {previous_content} [END]"
    print("Transform: Applied transformation to content")
    return StepOutput(
        step_name="TransformContent",
        content=transformed,
        success=True,
    )


# Registry (required to restore the executor function when loading)
registry = Registry(
    name="Custom Steps Registry",
    functions=[transform_content],
)

# ---------------------------------------------------------------------------
# Create Workflow Steps
# ---------------------------------------------------------------------------
# Steps
content_step = Step(
    name="CreateContent",
    description="Create initial content using the agent",
    agent=content_agent,
)

transform_step = Step(
    name="TransformContent",
    description="Transform the content using custom function",
    executor=transform_content,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
# Workflow
workflow = Workflow(
    name="Custom Executor Workflow",
    description="Create content with agent, then transform with custom function",
    steps=[
        content_step,
        transform_step,
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Run Workflow Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Save
    print("Saving workflow...")
    version = workflow.save(db=db)
    print(f"Saved workflow as version {version}")

    # Load
    print("\nLoading workflow...")
    loaded_workflow = get_workflow_by_id(
        db=db,
        id="custom-executor-workflow",
        registry=registry,
    )

    if loaded_workflow:
        print("Workflow loaded successfully!")
        print(f"  Name: {loaded_workflow.name}")
        print(f"  Steps: {len(loaded_workflow.steps) if loaded_workflow.steps else 0}")

        # Uncomment to run the loaded workflow
        # loaded_workflow.print_response(input="Write about AI trends", stream=True)
    else:
        print("Workflow not found")
