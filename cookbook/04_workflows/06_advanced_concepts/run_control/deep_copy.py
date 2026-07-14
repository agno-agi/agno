"""
Workflow Deep Copy
==================

Demonstrates creating isolated workflow copies with `deep_copy(update=...)`.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.workflow import Workflow
from agno.workflow.step import Step

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
outline_agent = Agent(
    name="Outline Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="Create a concise outline for the requested topic.",
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
outline_step = Step(name="Draft Outline", agent=outline_agent)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
base_workflow = Workflow(
    name="Base Editorial Workflow",
    description="Produces editorial outlines.",
    steps=[outline_step],
    session_id="base-session",
    session_state={"audience": "engineers", "tone": "concise"},
    metadata={"owner": "editorial"},
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    copied_workflow = base_workflow.deep_copy(
        update={
            "name": "Copied Editorial Workflow",
            "session_id": "copied-session",
        }
    )

    if copied_workflow.session_state is not None:
        copied_workflow.session_state["audience"] = "executives"
    if copied_workflow.metadata is not None:
        copied_workflow.metadata["owner"] = "growth"
    if isinstance(copied_workflow.steps, list) and copied_workflow.steps:
        copied_workflow.steps[0].name = "Draft Outline Copy"

    print("Original workflow")
    print(f"  Name: {base_workflow.name}")
    print(f"  Session ID: {base_workflow.session_id}")
    print(f"  Session State: {base_workflow.session_state}")
    print(f"  Metadata: {base_workflow.metadata}")
    if isinstance(base_workflow.steps, list) and base_workflow.steps:
        print(f"  First Step: {base_workflow.steps[0].name}")

    print("\nCopied workflow")
    print(f"  Name: {copied_workflow.name}")
    print(f"  Session ID: {copied_workflow.session_id}")
    print(f"  Session State: {copied_workflow.session_state}")
    print(f"  Metadata: {copied_workflow.metadata}")
    if isinstance(copied_workflow.steps, list) and copied_workflow.steps:
        print(f"  First Step: {copied_workflow.steps[0].name}")
