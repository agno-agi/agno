"""
Learning zone - Basic
=====================

Run the same typed arithmetic tasks several times, then keep the rows whose
binary outcomes disagree. Those rows have a true partial pass rate.
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
    name="first-learning-zone",
    agent=agent,
    tasks=(
        Task(id="easy-anchor", input="Multiply 17 by 23.", expected=391),
        Task(
            id="edge-e",
            input=(
                "Multiply 2718281828459045 by 1618033988749895. Add the decimal "
                "digits of the product, multiply that digit sum by 131071, then "
                "subtract the product's remainder modulo 65521."
            ),
            expected=20944939,
        ),
        Task(
            id="edge-pi",
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

    zone = result.learning_zone()
    print("Learning-zone rows:")
    for task_result in zone.task_results:
        print(f"  {task_result.task.id}: pass rate {task_result.pass_rate}")
