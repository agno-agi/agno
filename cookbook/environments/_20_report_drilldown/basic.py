"""
Report Drilldown - Basic
========================

The grid identifies a mixed task. The default report then expands only the attempts
worth investigating: scored failures plus anything unscored.
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
    name="report-drilldown-basic",
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
    results.print_report()
