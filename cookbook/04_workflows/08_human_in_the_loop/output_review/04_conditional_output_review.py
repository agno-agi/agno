"""
Conditional Output Review Example

This example demonstrates conditional HITL using the HITL config: the output
review only triggers when a condition is met. Instead of reviewing every output,
you can pass a callable predicate that decides at runtime whether review is needed.

In this example, only outputs longer than 200 characters trigger review.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, StepOutput
from agno.workflow.workflow import Workflow


def needs_review(step_output: StepOutput) -> bool:
    """Only review outputs longer than 200 characters."""
    content = str(step_output.content) if step_output.content else ""
    if len(content) > 200:
        print(f"[Review triggered: output is {len(content)} chars, threshold is 200]")
        return True
    print(f"[Auto-approved: output is only {len(content)} chars]")
    return False


draft_agent = Agent(
    name="Drafter",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You draft professional emails.",
)

send_agent = Agent(
    name="Sender",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You confirm sending the email. Summarize what was sent.",
)

workflow = Workflow(
    name="conditional_review_workflow",
    db=SqliteDb(db_file="tmp/output_review_conditional.db"),
    steps=[
        Step(
            name="draft_email",
            agent=draft_agent,
            human_review=HumanReview(
                # Pass a callable instead of a bool — only pauses when the predicate returns True
                requires_output_review=needs_review,
                output_review_message="Long email detected - please review before sending",
                on_reject=OnReject.retry,
                max_retries=2,
            ),
        ),
        Step(
            name="send_email",
            agent=send_agent,
        ),
    ],
)

run_output = workflow.run(
    "Draft a detailed email about Q4 planning, budget allocations, and team assignments"
)

while run_output.is_paused:
    for requirement in run_output.steps_requiring_output_review:
        print(
            f"\nOutput for review:\n{requirement.step_output.content if requirement.step_output else 'N/A'}"
        )

        choice = input("\nApprove? (yes/no): ").strip().lower()
        if choice in ("yes", "y"):
            requirement.confirm()
        else:
            feedback = input("Feedback: ")
            requirement.reject(feedback=feedback)

    run_output = workflow.continue_run(run_output)

print(f"\nFinal status: {run_output.status}")
print(f"Final output: {run_output.content}")
