"""Runnable companion to the account review guide."""

import json
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, StepInput, StepOutput

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------


def collect_account(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content=json.dumps(
            {
                "account": "Acme",
                "weekly_active_users": 18,
                "previous_week_active_users": 30,
                "open_support_tickets": 3,
            }
        )
    )


def save_review(step_input: StepInput) -> StepOutput:
    report = str(step_input.previous_step_content)
    Path("approved-review.md").write_text(report)
    return StepOutput(content="Saved approved-review.md")


reviewer = Agent(
    model=OpenAIResponses(id="gpt-5.6"),
    instructions=[
        "Write a short account review using only the supplied snapshot.",
        "Separate observed changes from possible explanations.",
        "Propose one follow-up question for the account owner.",
    ],
)

workflow = Workflow(
    id="account-review",
    name="Account Review",
    db=SqliteDb(db_file="account-review.db"),
    steps=[
        Step(name="Collect account", executor=collect_account),
        Step(name="Draft review", agent=reviewer),
        Step(
            name="Save approved review",
            executor=save_review,
            human_review=HumanReview(
                requires_confirmation=True,
                confirmation_message="Save this review to approved-review.md?",
            ),
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result = workflow.run("Review Acme's account activity.")
    while result.is_paused:
        for step in result.step_results:
            if isinstance(step, StepOutput) and step.step_name == "Draft review":
                print(step.content)
        for requirement in result.steps_requiring_confirmation:
            answer = input(f"{requirement.confirmation_message} [y/N] ")
            if answer.strip().lower() == "y":
                requirement.confirm()
            else:
                requirement.reject()
        result = workflow.continue_run(result)
    print(result.status)
    print(result.content)
