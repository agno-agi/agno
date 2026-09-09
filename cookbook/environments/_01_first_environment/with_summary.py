"""
Environment Summary
===================

Read the same rollout grid as a stable dictionary for scripts and CI. The
per-task rows expose pass rate, score mean, unscored attempts, and variation.
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


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Return only the requested final integer in the typed field.",
)

environment = Environment(
    name="summary-contract",
    agent=agent,
    tasks=(
        Task(input="What is 29 multiplied by 31?", expected=899, id="easy-product"),
        Task(
            input=(
                "Compute 2718281828459045 multiplied by 1618033988749895. "
                "Add its decimal digits, multiply that sum by 131071, subtract "
                "the product remainder modulo 65521, and return the result."
            ),
            expected=20944939,
            id="chained-product-a",
        ),
        Task(
            input=(
                "Compute 3141592653589793 multiplied by 1414213562373095. "
                "Add its decimal digits, multiply that sum by 65537, subtract "
                "the product remainder modulo 32749, and return the result."
            ),
            expected=10481347,
            id="chained-product-b",
        ),
    ),
    scorer=CodeScorer(answer_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
    print()

    summary = results.summary()
    print(f"overall pass rate: {summary['pass_rate']}")
    print(f"scored attempts: {summary['n_scored']} of {summary['n_attempts']}")
    for task in summary["tasks"]:
        print(
            f"{task['id']}: pass_rate={task['pass_rate']}, "
            f"unscored={task['n_unscored']}, learning_zone={task['learning_zone']}"
        )
