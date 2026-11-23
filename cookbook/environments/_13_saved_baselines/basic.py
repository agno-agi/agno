"""
Saved Baselines - Basic
=======================

Save a complete rollout result for a later compatible comparison. The artifact
contains transcripts, so store it with the same care as the evaluated prompts.
"""

from pathlib import Path

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
    name="saved-baseline-basic",
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
            id="product-d",
            input=(
                "Compute 2236067977499789 times 2449489742783178. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "524287, subtract the product remainder modulo 99991, and "
                "return the final integer."
            ),
            expected=76998482,
        ),
    ),
    scorer=CodeScorer(exact_value),
)

baseline_path = Path(__file__).parent / "data" / "generated" / "baseline.json"


if __name__ == "__main__":
    result = run_rollouts(env, k=6)
    print(result)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(baseline_path)
    print(f"saved {result.n_attempts} attempts to {baseline_path}")
