"""
CodeScorer - Basic
==================

Turn a typed model field into a deterministic pass or fail. Boolean code
scores make score variation and a partial pass-rate learning zone coincide.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int


def exact_value(run, expected):
    return run.content.value == expected


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Return only the requested final integer in the typed field.",
)

environment = Environment(
    name="boolean-code-scorer",
    agent=agent,
    tasks=(
        Task(
            input=(
                "Compute 2718281828459045 multiplied by 1618033988749895. "
                "Add its decimal digits, multiply the sum by 131071, subtract "
                "the product remainder modulo 65521, and return the result."
            ),
            expected=20944939,
            id="chained-product-a",
        ),
        Task(
            input=(
                "Compute 3141592653589793 multiplied by 1414213562373095. "
                "Add its decimal digits, multiply the sum by 104729, subtract "
                "the product remainder modulo 65537, and return the result."
            ),
            expected=16731173,
            id="chained-product-b",
        ),
    ),
    scorer=CodeScorer(exact_value),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
    print()
    for task_result in results.task_results:
        print(
            f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}, "
            f"learning_zone={task_result.in_learning_zone}"
        )
