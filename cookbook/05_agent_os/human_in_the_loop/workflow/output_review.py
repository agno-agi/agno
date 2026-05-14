"""
Output Review HITL Example (AgentOS)

This example demonstrates pausing after a step runs so a human can review the
step output before the workflow continues in AgentOS.
"""

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.workflow import HumanReview, OnReject
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

db = SqliteDb(db_file="tmp/agentos_workflow_output_review.db")


def draft_email(step_input: StepInput) -> StepOutput:
    topic = step_input.input or "the schedule change"
    return StepOutput(
        content=f"Subject: Update: {topic}\n\n"
        "Hi team,\n\n"
        f"Please note that {topic}. Let me know if this creates any conflicts.\n\n"
        "Thanks"
    )


def send_email(step_input: StepInput) -> StepOutput:
    approved_draft = step_input.previous_step_content or "No approved draft"
    return StepOutput(content=f"Email queued for sending:\n\n{approved_draft}")


workflow = Workflow(
    name="output_review_workflow",
    description="Review a drafted email before it moves to the send step.",
    db=db,
    steps=[
        Step(
            name="draft_email",
            executor=draft_email,
            human_review=HumanReview(
                requires_output_review=True,
                output_review_message="Review this email draft before sending.",
                on_reject=OnReject.cancel,
            ),
        ),
        Step(name="send_email", executor=send_email),
    ],
)
workflow.id = "workflow-hitl-output-review"

agent_os = AgentOS(
    name="Workflow Output Review HITL",
    description="AgentOS workflow example for post-step output review.",
    workflows=[workflow],
    db=db,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="output_review:app", reload=True)
