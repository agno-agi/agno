"""
Report Drilldown - Single Attempt
=================================

Select the first scored failure from the retained result and render its complete
transcript. Attempt numbers are one-based, matching the glyph positions in the grid.
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
        max_output_tokens=2500,
    ),
    instructions="Solve exactly without external tools and return the final integer.",
    output_schema=Answer,
)

env = Environment(
    name="single-attempt-report",
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
    ),
    scorer=CodeScorer(exact),
)


if __name__ == "__main__":
    results = run_rollouts(env, k=8, concurrency=4)
    print(results)
    print()

    task_result = results.task_results[0]
    failed_attempt = next(
        (
            index
            for index, attempt in enumerate(task_result.attempts, start=1)
            if attempt.score is not None and not attempt.score.passed
        ),
        None,
    )
    if failed_attempt is None:
        print(
            "No scored failure was retained. Recalibrate the task before using this "
            "example as failure evidence."
        )
        if task_result.n_unscored:
            print(f"unscored attempts retained: {task_result.n_unscored}")
    else:
        results.print_attempt("hard-product", failed_attempt)
