"""
Learning zone - Saturated tasks
===============================

Easy rows establish that the runner works, but a wall of full bars teaches
nothing about the policy boundary. Keep them as anchors and calibrate harder
rows until the same grid contains real disagreement.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class FinalInteger(BaseModel):
    value: int = Field(description="The final integer after every requested operation")


def exact_integer(run, expected) -> bool:
    return isinstance(run.content, FinalInteger) and run.content.value == expected


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    instructions="Calculate exactly. Return only the final integer in the response schema.",
    output_schema=FinalInteger,
)

env = Environment(
    name="saturation-contrast",
    agent=agent,
    tasks=(
        Task(id="saturated-17x23", input="Multiply 17 by 23.", expected=391),
        Task(
            id="saturated-two-step",
            input="Multiply 127 by 89, then subtract 41.",
            expected=11262,
        ),
        Task(
            id="calibrated-edge-a",
            input=(
                "Multiply 2718281828459045 by 1618033988749895. Add the decimal "
                "digits of the product, multiply that digit sum by 131071, then "
                "subtract the product's remainder modulo 65521."
            ),
            expected=20944939,
        ),
        Task(
            id="calibrated-edge-b",
            input=(
                "Multiply 3141592653589793 by 1414213562373095. Add the decimal "
                "digits of the product, multiply that digit sum by 65537, then "
                "subtract the product's remainder modulo 32749."
            ),
            expected=10481347,
        ),
    ),
    scorer=CodeScorer(exact_integer),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=4, concurrency=4)
    print(result)
    print(
        "Rows at 1.0 are anchors; rows strictly between 0 and 1 carry learning signal."
    )
    for task_result in result.task_results:
        print(f"  {task_result.task.id}: pass rate {task_result.pass_rate}")
