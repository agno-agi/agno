"""
Math - Basic
============

One multiplication is too easy for a strong model. Put it beside a recurrence whose
repeated squaring and modulus create a genuine pass-rate distribution.
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
    name="math-basic",
    agent=agent,
    tasks=(
        Task(id="single-product", input="What is 17 x 23?", expected=391),
        Task(
            id="recurrence-8",
            input=(
                "Let a0=271828. For n=1 through 8, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_8."
            ),
            expected=6856135,
        ),
    ),
    scorer=CodeScorer(exact),
)


if __name__ == "__main__":
    results = run_rollouts(env, k=6, concurrency=6)
    print(results)

    for task in results.summary()["tasks"]:
        print(f"{task['id']}: pass_rate={task['pass_rate']}")
