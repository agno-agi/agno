"""
Environment Diff - Task Subset
==============================

A selection made from env.tasks keeps the same environment identity. The diff
compares shared rows and reports baseline-only rows instead of hiding them.
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
)

env = Environment(
    name="environment-diff-subset",
    agent=agent,
    tasks=(
        Task(
            id="product-a",
            input=(
                "Compute 2718281828459045 times 1618033988749895. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "131071, subtract the product remainder modulo 65521, and "
                "return the final integer."
            ),
            expected=20944939,
        ),
        Task(
            id="product-b",
            input=(
                "Compute 3141592653589793 times 2718281828459045. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "104729, subtract the product remainder modulo 65537, and "
                "return the final integer."
            ),
            expected=16756170,
        ),
    ),
    scorer=CodeScorer(exact_value),
)


if __name__ == "__main__":
    baseline = run_rollouts(env, k=4)
    selected = [task for task in env.tasks if task.id == "product-a"]
    candidate = run_rollouts(
        env,
        k=4,
        tasks=selected,
        model=OpenAIResponses(id="gpt-5.5", reasoning_effort="high"),
    )
    print(baseline)
    print(candidate)
    diff = candidate.diff(baseline)
    print(diff)
    print(f"baseline-only tasks: {list(diff.unmatched_baseline)}")
