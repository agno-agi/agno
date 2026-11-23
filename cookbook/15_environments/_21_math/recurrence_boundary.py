"""
Math - Recurrence Boundary
==========================

Grow one recurrence by a single round at a time. All three rows are deterministic;
the pass-rate grid reveals where repeated exact state updates strain the policy.
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
    instructions="Compute the recurrence exactly and return the final integer.",
    output_schema=Answer,
)

env = Environment(
    name="recurrence-boundary",
    agent=agent,
    tasks=(
        Task(
            id="rounds-8",
            input=(
                "Let a0=271828. For n=1 through 8, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_8."
            ),
            expected=6856135,
        ),
        Task(
            id="rounds-9",
            input=(
                "Let a0=271828. For n=1 through 9, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_9."
            ),
            expected=7826798,
        ),
        Task(
            id="rounds-10",
            input=(
                "Let a0=271828. For n=1 through 10, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_10."
            ),
            expected=542370,
        ),
    ),
    scorer=CodeScorer(exact),
)


if __name__ == "__main__":
    results = run_rollouts(env, k=6, concurrency=6)
    print(results)

    for task in results.task_results:
        print(f"{task.task.id}: {task.n_passed}/{task.n_scored}")
