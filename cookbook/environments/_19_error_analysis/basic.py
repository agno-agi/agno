"""
Error Analysis - Basic
======================

Keep wrong answers separate from attempts that could not be scored. The hard row
produces a real pass-rate distribution; the second row raises inside the scorer so
the unscored evidence is visible without relying on a provider failure.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Schema and Scorer
# ---------------------------------------------------------------------------
class Answer(BaseModel):
    value: int


def exact_or_raise(run, expected):
    if expected["raise"]:
        raise RuntimeError("deliberate scorer failure for inspection")
    if run.content is None:
        # A truncated attempt (max_output_tokens) has no parsed output. Raise a clear
        # error so the runner records it unscored -- a no-answer, not a wrong answer.
        raise ValueError("no parsed output: hit max_output_tokens")
    return run.content.value == expected["value"]


# ---------------------------------------------------------------------------
# Create Environment
# ---------------------------------------------------------------------------
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
    name="error-analysis-basic",
    agent=agent,
    tasks=(
        Task(
            id="hard-product",
            input=(
                "Compute 2718281828459045 x 1618033988749895. Add every "
                "decimal digit of the product, multiply that sum by 131071, "
                "then subtract the product remainder modulo 65521."
            ),
            expected={"value": 20944939, "raise": False},
        ),
        Task(
            id="scorer-outage",
            input="What is 17 x 23?",
            expected={"value": 391, "raise": True},
        ),
    ),
    scorer=CodeScorer(exact_or_raise),
)


# ---------------------------------------------------------------------------
# Run and Inspect
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    results = run_rollouts(env, k=8, concurrency=4)
    print(results)
    print()

    summary = results.summary()
    print(f"scored attempts: {summary['n_scored']}")
    print(f"unscored attempts: {summary['n_unscored']}")
    print(f"pass rate over scored attempts: {summary['pass_rate']}")
    print(f"errors by task: {results.errors()}")
