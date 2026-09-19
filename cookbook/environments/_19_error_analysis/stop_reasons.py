"""
Error Analysis - Stop Reasons
=============================

Every attempt retains a public StopReason. Count those reasons before interpreting a
pass rate so a timeout or verifier exception is never mistaken for a wrong answer.
"""

from collections import Counter

from agno.agent import Agent
from agno.environments import (
    AttemptResult,
    Environment,
    StopReason,
    Task,
    TaskResult,
    run_rollouts,
)
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int


def exact_or_unscorable(run, expected):
    if expected == "unscorable":
        raise RuntimeError("deliberate verifier exception")
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
    name="stop-reason-inspection",
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
        Task(id="verifier-error", input="What is 17 x 23?", expected="unscorable"),
    ),
    scorer=CodeScorer(exact_or_unscorable),
)


def attempts(task_result: TaskResult) -> tuple[AttemptResult, ...]:
    """Expose the public result types used beneath every grid row."""
    return task_result.attempts


if __name__ == "__main__":
    results = run_rollouts(env, k=8, concurrency=4)
    print(results)
    print()

    reason_counts = Counter(
        attempt.stop_reason
        for task_result in results.task_results
        for attempt in attempts(task_result)
    )
    for reason in StopReason:
        print(f"{reason.value}: {reason_counts[reason]}")

    print(f"unscored attempts: {results.n_unscored}")
