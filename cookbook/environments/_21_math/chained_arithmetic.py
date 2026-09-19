"""
Math - Chained Arithmetic
=========================

Make arithmetic learnable by composing individually simple operations. A verifier
still compares one typed integer, but the agent must carry the exact product through
a digit transform, a scale, and a modulus adjustment.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int


def exact(run, expected):
    return run.content.value == expected


agent = Agent(
    model=OpenAIResponses(
        id="gpt-5.5",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=3000,
    ),
    instructions="Compute exactly without external tools and return the final integer.",
    output_schema=Answer,
)

env = Environment(
    name="chained-arithmetic",
    agent=agent,
    tasks=(
        Task(
            id="short-chain",
            input=(
                "Compute 9999999967 x 9999999973. Add every decimal digit of "
                "the product, multiply that sum by 104729, then subtract the "
                "product remainder modulo 7919."
            ),
            expected=9838934,
        ),
        Task(
            id="long-chain",
            input=(
                "Compute 2718281828459045 x 1618033988749895. Add every "
                "decimal digit of the product, multiply that sum by 131071, "
                "then subtract the product remainder modulo 65521."
            ),
            expected=20944939,
        ),
    ),
    scorer=CodeScorer(exact),
)


if __name__ == "__main__":
    results = run_rollouts(env, k=6, concurrency=6)
    print(results)

    middle = [
        task.task.id
        for task in results.task_results
        if task.pass_rate is not None and 0 < task.pass_rate < 1
    ]
    print(f"partial pass-rate tasks: {middle}")
