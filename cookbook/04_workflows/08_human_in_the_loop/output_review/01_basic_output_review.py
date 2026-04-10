"""
Basic Output Review Example

This example demonstrates post-execution output review using the HITL config,
where the workflow pauses AFTER a step runs so a human can review the output
before it flows to the next step.

The human can:
- Confirm: Output flows to the next step as-is
- Reject with on_reject=OnReject.skip: Output is discarded, step is skipped
- Reject with on_reject=OnReject.cancel: Workflow is cancelled
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.types import HumanReview
from agno.workflow.workflow import Workflow

# Create agents for each step
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

# Create a workflow where the draft step requires human review before proceeding
workflow = Workflow(
    name="email_workflow",
    db=SqliteDb(db_file="tmp/output_review.db"),
    steps=[
        Step(
            name="draft_email",
            agent=draft_agent,
            human_review=HumanReview(
                requires_output_review=True,
                output_review_message="Review the email draft before sending",
                on_reject=OnReject.cancel,  # Reject = cancel workflow (don't send the email)
            ),
        ),
        Step(
            name="send_email",
            agent=send_agent,
        ),
    ],
)

# Run the workflow
run_output = workflow.run(
    "Draft an email to the team about the Friday standup being moved to Monday"
)

# The workflow pauses after draft_email runs, before send_email starts
if run_output.is_paused:
    for requirement in run_output.steps_requiring_output_review:
        print(f"\nStep '{requirement.step_name}' produced output for review:")
        print(f"Message: {requirement.output_review_message}")
        print(
            f"\nOutput:\n{requirement.step_output.content if requirement.step_output else 'N/A'}"
        )

        # Wait for user input
        user_input = input("\nApprove this output? (yes/no): ").strip().lower()

        if user_input in ("yes", "y"):
            requirement.confirm()
            print("Output approved - continuing to next step.")
        else:
            requirement.reject()
            print("Output rejected.")

    # Continue the workflow
    run_output = workflow.continue_run(run_output)

print(f"\nFinal status: {run_output.status}")
print(f"Final output: {run_output.content}")
