"""
HITL Timeout Example

This example demonstrates timeout handling for HITL pauses using the HumanReview
config class. When a step pauses for human review, a timeout can be set so
the workflow doesn't wait forever.

Timeout is checked at continue_run() time. If the timeout has elapsed:
- on_timeout="approve": Auto-approve the output
- on_timeout="skip": Skip the step
- on_timeout="cancel": Cancel the workflow

For real applications, the frontend/API layer would call continue_run()
when the timeout expires, and the timeout_at field is available in the
StepRequirement for UI countdown display.
"""

import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnTimeout
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
    name="timeout_workflow",
    db=SqliteDb(db_file="tmp/output_review_timeout.db"),
    steps=[
        Step(
            name="draft_email",
            agent=draft_agent,
            human_review=HumanReview(
                requires_output_review=True,
                output_review_message="Review the draft (auto-approves in 5 seconds)",
                timeout=5,  # 5 second timeout
                on_timeout=OnTimeout.approve,  # Auto-approve when timeout expires
            ),
        ),
        Step(
            name="send_email",
            agent=send_agent,
        ),
    ],
)

run_output = workflow.run("Draft an email about the team lunch next Thursday")

if run_output.is_paused:
    for requirement in run_output.steps_requiring_output_review:
        print(
            f"\nDraft output:\n{requirement.step_output.content if requirement.step_output else 'N/A'}"
        )
        print(f"\nTimeout at: {requirement.timeout_at}")
        print(f"On timeout: {requirement.on_timeout}")

    # Simulate waiting past the timeout
    print("\nSimulating 6 second delay (timeout is 5 seconds)...")
    time.sleep(6)

    # When continue_run is called, it checks timeout and auto-resolves
    run_output = workflow.continue_run(run_output)
    print("\nAuto-resolved by timeout!")

print(f"\nFinal status: {run_output.status}")
print(f"Final output: {run_output.content}")
