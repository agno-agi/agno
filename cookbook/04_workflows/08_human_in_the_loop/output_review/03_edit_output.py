"""
Edit Output Example

This example demonstrates human editing of step output using the HITL config.
Instead of rejecting and retrying (which costs another LLM call), the human
directly modifies the output before it flows to the next step.

The human can:
- confirm(): Accept the output as-is
- reject(): Reject (skip/cancel/retry depending on on_reject)
- edit(new_output): Accept with modifications
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
    name="email_edit_workflow",
    db=SqliteDb(db_file="tmp/output_review_edit.db"),
    steps=[
        Step(
            name="draft_email",
            agent=draft_agent,
            human_review=HumanReview(
                requires_output_review=True,
                output_review_message="Review and optionally edit the email draft",
                on_reject=OnReject.cancel,
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

if run_output.is_paused:
    for requirement in run_output.steps_requiring_output_review:
        print(
            f"\nDraft output:\n{requirement.step_output.content if requirement.step_output else 'N/A'}"
        )

        choice = input("\n[a]pprove / [e]dit / [r]eject: ").strip().lower()

        if choice == "a":
            requirement.confirm()
        elif choice == "e":
            edited = input("Enter your edited version:\n")
            requirement.edit(edited)
            print("Output replaced with your edit.")
        else:
            requirement.reject()
            print("Draft rejected - cancelling workflow.")

    run_output = workflow.continue_run(run_output)

print(f"\nFinal status: {run_output.status}")
print(f"Final output: {run_output.content}")
