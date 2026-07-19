"""
Loop Iterative Accumulation
============================

Demonstrates that Loop iterations carry forward the output from the previous iteration.
Each iteration receives the previous iteration's output via `step_input.get_last_step_content()`,
enabling iterative processing patterns like accumulation, refinement, and convergence.

This example increments a numeric value by 10 each iteration, stopping when it reaches 50 or more.
Starting from 35, the loop should:
  - Iteration 1: 35 -> 45
  - Iteration 2: 45 -> 55 (>= 50, end condition met)
"""

from agno.workflow import Loop, Step, Workflow
from agno.workflow.types import StepInput, StepOutput


def increment_executor(step_input: StepInput) -> StepOutput:
    """Increment the previous step's numeric content by 10."""
    last_content = step_input.get_last_step_content()
    if last_content and last_content.isdigit():
        new_value = int(last_content) + 10
        return StepOutput(content=str(new_value))
    return StepOutput(content="0")


workflow = Workflow(
    name="Iterative Accumulation Workflow",
    description="Demonstrates loop iterations carrying forward output from previous iterations.",
    steps=[
        Step(
            name="Initial Value",
            description="Pass through the initial input value.",
            executor=lambda step_input: StepOutput(content=step_input.input),
        ),
        Loop(
            name="Increment Loop",
            description="Increment value by 10 each iteration until it reaches 50.",
            steps=[
                Step(
                    name="Increment Step",
                    description="Add 10 to the current value.",
                    executor=increment_executor,
                )
            ],
            end_condition=lambda step_outputs: int(step_outputs[-1].content) >= 50,
            max_iterations=10,
            forward_iteration_output=True,
        ),
    ],
)

if __name__ == "__main__":
    workflow.print_response("35")
