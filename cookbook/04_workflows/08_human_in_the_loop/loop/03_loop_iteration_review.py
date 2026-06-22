"""
Loop Iteration Review Example

This example demonstrates per-iteration review in a Loop component using
the HITL config class. After each iteration completes, the workflow pauses
for human review.

The reviewer can:
- Accept (confirm): Stop the loop, keep the current output
- Reject (try again): Run another iteration, optionally with feedback
  The previous iteration's output is forwarded as input so the agent
  can continue refining it.

  Loop topology:
    iteration 1 -> [review] -+- accept -> done (keep output)
                              +- reject (with feedback) -> iteration 2 -> [review] -> ...
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow import OnReject
from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.types import HumanReview
from agno.workflow.workflow import Workflow

refine_agent = Agent(
    name="Refiner",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=(
        "You refine and improve text. Each time you receive text, "
        "make it more concise and polished. If the reviewer provides feedback, "
        "incorporate it. Return only the improved text."
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
            human_review=HumanReview(
                requires_iteration_review=True,
                iteration_review_message="Review this iteration.",
                on_reject=OnReject.retry,  # Reject = try another iteration
            ),
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

        choice = input("\nAccept this result? (yes/no): ").strip().lower()
        if choice in ("yes", "y"):
            requirement.confirm()
            print("Result accepted.")
        else:
            feedback = input("Feedback (press Enter to skip): ").strip()
            if feedback:
                requirement.reject(feedback=feedback)
            else:
                requirement.reject()
            print("Trying another iteration...")

    run_output = workflow.continue_run(run_output)

print(f"\nFinal status: {run_output.status}")
print(f"Final output: {run_output.content}")
