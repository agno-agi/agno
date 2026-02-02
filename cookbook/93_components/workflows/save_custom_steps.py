"""
Example: Saving and Loading a Workflow with Custom Executor Steps

This example demonstrates how to:
1. Create a workflow with custom executor functions (not agents)
2. Save the workflow to a database
3. Load the workflow back using a registry to restore the executor function
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.registry import Registry
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow, get_workflow_by_id

# Database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Agents
content_agent = Agent(
    name="Content Creator",
    instructions="Create well-structured content from input data",
)


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
