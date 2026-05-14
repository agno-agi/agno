"""
Step Confirmation HITL Example (AgentOS)

This example demonstrates pausing a workflow before a step executes so the
human can approve or reject that step from AgentOS.
"""

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

db = SqliteDb(db_file="tmp/agentos_workflow_step_confirmation.db")


def fetch_data(step_input: StepInput) -> StepOutput:
    topic = step_input.input or "user data"
    return StepOutput(
        content=f"Fetched records for '{topic}'.\n"
        "- 250 records found\n"
        "- Sensitive fields detected\n"
        "- Ready for processing"
    )


def process_sensitive_data(step_input: StepInput) -> StepOutput:
    previous_content = step_input.previous_step_content or "No fetched data"
    return StepOutput(
        content=f"Processed sensitive data:\n\n{previous_content}\n\n"
        "- PII fields masked\n"
        "- Aggregations calculated\n"
        "- Processing audit created"
    )


def save_results(step_input: StepInput) -> StepOutput:
    previous_content = step_input.previous_step_content or "No processed data"
    return StepOutput(
        content=f"Saved workflow results.\n\nFinal payload:\n{previous_content}"
    )


workflow = Workflow(
    name="step_confirmation_workflow",
    description="Pause before processing sensitive data and continue through AgentOS.",
    db=db,
    steps=[
        Step(name="fetch_data", executor=fetch_data),
        Step(
            name="process_sensitive_data",
            executor=process_sensitive_data,
            requires_confirmation=True,
            confirmation_message="Process sensitive data now?",
            on_reject=OnReject.skip,
        ),
        Step(name="save_results", executor=save_results),
    ],
)
workflow.id = "workflow-hitl-step-confirmation"

agent_os = AgentOS(
    name="Workflow Step Confirmation HITL",
    description="AgentOS workflow example for step-level confirmation.",
    workflows=[workflow],
    db=db,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="step_confirmation:app", reload=True)
