"""
Error Analysis - Scorer Errors
==============================

A verifier bug should not erase the rest of a rollout batch. This example makes one
task's verifier fail deliberately, then shows that the difficult task still retains
all of its scored attempts and its partial pass rate.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int


def verifier_with_fault(run, expected):
    if expected is None:
        raise ValueError("expected answer is missing")
    if run.content is None:
        raise ValueError("no parsed output: hit max_output_tokens")
    return run.content.value == expected


agent = Agent(
    model=OpenAIResponses(
        id="gpt-5.5",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=2500,
    ),
    instructions="Solve exactly without external tools and return the final integer.",
    output_schema=Answer,
)

env = Environment(
    name="scorer-error-capture",
    agent=agent,
    tasks=(
        Task(
            id="hard-product",
            input=(
                "Compute 2718281828459045 x 1618033988749895. Add every "
                "decimal digit of the product, multiply that sum by 131071, "
                "then subtract the product remainder modulo 65521."
            ),
            expected=20944939,
        ),
        Task(id="missing-gold", input="What is 17 x 23?"),
    ),
    scorer=CodeScorer(verifier_with_fault),
)


if __name__ == "__main__":
    results = run_rollouts(env, k=8, concurrency=4)
    print(results)
    print()

    for task in results.task_results:
        print(
            f"{task.task.id}: scored={task.n_scored}, "
            f"unscored={task.n_unscored}, pass_rate={task.pass_rate}"
        )

    print(f"captured scorer errors: {results.errors()}")
