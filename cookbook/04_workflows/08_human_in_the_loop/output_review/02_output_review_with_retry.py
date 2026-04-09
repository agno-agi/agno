"""
Output Review with Retry Example

This example demonstrates the reject-with-feedback-and-retry pattern using
the HITL config:
1. Agent produces output
2. Human reviews and rejects with feedback ("too formal, make it casual")
3. Agent retries with the feedback
4. Human reviews again and approves

Uses on_reject=OnReject.retry with reject(feedback=...) to send
feedback to the agent on retry.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.types import HumanReview
from agno.workflow.workflow import Workflow

draft_agent = Agent(
    name="Drafter",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You draft short professional emails. Keep it under 3 sentences.",
)

send_agent = Agent(
    name="Sender",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You confirm sending the email. Summarize what was sent.",
)

workflow = Workflow(
    name="email_review_workflow",
    db=SqliteDb(db_file="tmp/output_review_retry.db"),
    steps=[
        Step(
            name="draft_email",
            agent=draft_agent,
            human_review=HumanReview(
                requires_output_review=True,
                output_review_message="Review the email draft before sending",
                on_reject=OnReject.retry,  # Re-run the step on rejection
                max_retries=3,  # Maximum 3 retry attempts
            ),
        ),
        Step(
            name="send_email",
            agent=send_agent,
        ),
    ],
)

run_output = workflow.run(
    "Draft an email to the team about the Friday standup being moved to Monday"
)

while run_output.is_paused:
    for requirement in run_output.steps_requiring_output_review:
        print(
            f"\nStep '{requirement.step_name}' output (attempt {requirement.retry_count + 1}):"
        )
        print(
            f"{requirement.step_output.content if requirement.step_output else 'N/A'}"
        )

        user_input = input("\nApprove? (yes/no): ").strip().lower()

        if user_input in ("yes", "y"):
            requirement.confirm()
        else:
            feedback = input("What should change? ")
            requirement.reject(feedback=feedback)
            print("Rejected with feedback. Retrying...")

    run_output = workflow.continue_run(run_output)

print(f"\nFinal status: {run_output.status}")
print(f"Final output: {run_output.content}")
