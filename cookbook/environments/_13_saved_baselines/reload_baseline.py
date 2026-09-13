"""
Saved Baselines - Reload
========================

Save and reload the result, then compare the stable summary fields that a later
verification or CI job can consume.
"""

from pathlib import Path

from agno.agent import Agent
from agno.environments import Environment, EnvironmentRunResult, Task, run_rollouts
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
    name="reload-saved-baseline",
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
            id="product-c",
            input=(
                "Compute 1414213562373095 times 1732050807568877. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "99991, subtract the product remainder modulo 32749, and "
                "return the final integer."
            ),
            expected=16568751,
        ),
    ),
    scorer=CodeScorer(exact_value),
)

baseline_path = Path(__file__).parent / "data" / "generated" / "reloaded.json"


if __name__ == "__main__":
    result = run_rollouts(env, k=4)
    print(result)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(baseline_path)

    loaded = EnvironmentRunResult.load(baseline_path)
    assert loaded.summary() == result.summary()
    print(f"reloaded pass rate: {loaded.pass_rate}")
    print(f"fingerprints preserved: {loaded.env_fingerprint == result.env_fingerprint}")
