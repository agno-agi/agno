"""
Loop Iteration Review Example

This example demonstrates per-iteration review in a Loop component.
After each iteration completes, the workflow pauses for human review
before starting the next iteration.

The human can:
- Confirm: Continue to the next iteration
- Reject with on_reject=OnReject.skip: Stop the loop early
- Reject with on_reject=OnReject.cancel: Cancel the entire workflow
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.workflow import OnReject
from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

refine_agent = Agent(
    name="Refiner",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=(
        "You refine and improve text. Each time you receive text, "
        "make it more concise and polished. Return only the improved text."
    ),
)

workflow = Workflow(
    name="iterative_refinement",
    db=SqliteDb(db_file="tmp/loop_iteration_review.db"),
    steps=[
        Loop(
            name="refinement_loop",
            steps=[
                Step(name="refine", agent=refine_agent),
            ],
            max_iterations=5,
            forward_iteration_output=True,
            requires_iteration_review=True,
            iteration_review_message="Review this iteration. Continue refining?",
            on_reject=OnReject.skip,  # Stop loop early if rejected
        ),
    ],
)

run_output = workflow.run(
    "The quick brown fox jumped over the lazy dog and then it went to the store "
    "to buy some groceries because it was hungry and needed food to eat."
)

while run_output.is_paused:
    for requirement in run_output.steps_requiring_output_review:
        print(f"\n{requirement.confirmation_message}")
        print(
            f"\nCurrent output:\n{requirement.step_output.content if requirement.step_output else 'N/A'}"
        )

        choice = input("\nContinue refining? (yes/no): ").strip().lower()
        if choice in ("yes", "y"):
            requirement.confirm()
        else:
            requirement.reject()
            print("Stopping refinement loop.")

    run_output = workflow.continue_run(run_output)

print(f"\nFinal status: {run_output.status}")
print(f"Final output: {run_output.content}")
