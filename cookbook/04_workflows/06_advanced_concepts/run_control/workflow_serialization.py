"""
Workflow Serialization
======================

Demonstrates `to_dict()`, `save()`, and `load()` for workflow persistence.
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow import Workflow
from agno.workflow.step import Step

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
research_agent = Agent(
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="Research the topic and gather key findings.",
)

writer_agent = Agent(
    name="Writer Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="Turn research notes into a concise summary.",
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_step = Step(name="Research", agent=research_agent)
write_step = Step(name="Write", agent=writer_agent)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow_db = SqliteDb(
    db_file="tmp/workflow_serialization.db", session_table="workflow_serialization"
)

workflow = Workflow(
    id="serialization-demo-workflow",
    name="Serialization Demo Workflow",
    description="Workflow used to demonstrate serialization and persistence APIs.",
    db=workflow_db,
    steps=[research_step, write_step],
    metadata={"owner": "cookbook", "topic": "serialization"},
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    workflow_dict = workflow.to_dict()
    print("Serialized workflow dictionary")
    print(json.dumps(workflow_dict, indent=2)[:1200])

    version = workflow.save(db=workflow_db, label="serialization-demo")
    print(f"\nSaved workflow version: {version}")

    loaded_workflow = Workflow.load(
        id="serialization-demo-workflow",
        db=workflow_db,
        label="serialization-demo",
    )

    if loaded_workflow is None:
        print("Failed to load workflow from the database.")
    else:
        step_names = []
        if isinstance(loaded_workflow.steps, list):
            step_names = [
                step.name for step in loaded_workflow.steps if hasattr(step, "name")
            ]

        print("\nLoaded workflow summary")
        print(f"  Name: {loaded_workflow.name}")
        print(f"  Description: {loaded_workflow.description}")
        print(f"  Steps: {step_names}")
