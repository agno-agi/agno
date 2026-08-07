"""
Learning zone - Select the middle band
======================================

For binary scores, make the cookbook definition explicit: retain a row only
when its observed pass rate is greater than zero and less than one.
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
    name="middle-band-selection",
    agent=agent,
    tasks=(
        Task(id="easy", input="Multiply 29 by 31.", expected=899),
        Task(
            id="candidate-a",
            input=(
                "Multiply 2718281828459045 by 1618033988749895. Add the decimal "
                "digits of the product, multiply that digit sum by 131071, then "
                "subtract the product's remainder modulo 65521."
            ),
            expected=20944939,
        ),
        Task(
            id="candidate-b",
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

    middle_band = [
        task_result
        for task_result in result.task_results
        if task_result.pass_rate is not None and 0 < task_result.pass_rate < 1
    ]
    print("Strict partial-pass-rate rows:")
    for task_result in middle_band:
        print(f"  {task_result.task.id}: pass rate {task_result.pass_rate}")
