"""
Task Sets - Basic
=================

Give every task a durable id and an expected value. The id labels the grid
and becomes the join key for saved baselines and later comparisons.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int


def answer_matches(run, expected):
    return run.content.value == expected


TASKS = (
    Task(input="What is 43 multiplied by 47?", expected=2021, id="easy-product"),
    Task(
        input=(
            "Compute 2718281828459045 multiplied by 1618033988749895. Add "
            "the product's decimal digits, multiply the sum by 131071, "
            "subtract the product remainder modulo 65521, and return the result."
        ),
        expected=20944939,
        id="chained-product-a",
    ),
    Task(
        input=(
            "Compute two chained values, then add them. First: multiply "
            "2718281828459045 by 1618033988749895, add the product's decimal "
            "digits, multiply that sum by 131071, and subtract the product "
            "remainder modulo 65521. Second: multiply 3141592653589793 by "
            "1414213562373095, add the product's decimal digits, multiply that "
            "sum by 104729, and subtract the product remainder modulo 65537. "
            "Return the sum of the two chained values."
        ),
        expected=37676112,
        id="dual-chain-sum",
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Return only the requested final integer in the typed field.",
)

environment = Environment(
    name="task-set-basics",
    agent=agent,
    tasks=TASKS,
    scorer=CodeScorer(answer_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
    print()
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
