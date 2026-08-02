"""
Difficulty calibration - Basic
==============================

Build a ladder rather than guessing that a task is hard. Repeated pass rates
show where the current policy moves from mastery into inconsistent execution.
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
    name="difficulty-ladder",
    agent=agent,
    tasks=(
        Task(id="one-step", input="Multiply 43 by 67.", expected=2881),
        Task(
            id="three-step",
            input="Multiply 4319 by 7877, add its decimal digits, then multiply by 97.",
            expected=2425,
        ),
        Task(
            id="edge-a",
            input=(
                "Multiply 2718281828459045 by 1618033988749895. Add the decimal "
                "digits of the product, multiply that digit sum by 131071, then "
                "subtract the product's remainder modulo 65521."
            ),
            expected=20944939,
        ),
        Task(
            id="edge-b",
            input=(
                "Multiply 3162277660168379 by 2236067977499789. Add the decimal "
                "digits of the product, multiply that digit sum by 131101, then "
                "subtract the product's remainder modulo 32771."
            ),
            expected=18992769,
        ),
    ),
    scorer=CodeScorer(exact_integer),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=4, concurrency=4)
    print(result)
    for task_result in result.task_results:
        print(f"{task_result.task.id}: pass rate {task_result.pass_rate}")
