"""
Policy Settings - Reasoning Effort
==================================

Inspect why low and high reasoning settings are comparable: one environment
fingerprint, two policy fingerprints, and task-level pass-rate deltas.
"""

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
    name="reasoning-effort-policy",
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
            id="product-e",
            input=(
                "Compute 3162277660168379 times 2645751311064591. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "131101, subtract the product remainder modulo 65519, and "
                "return the final integer."
            ),
            expected=20389256,
        ),
    ),
    scorer=CodeScorer(exact_value),
)


if __name__ == "__main__":
    low = run_rollouts(env, k=4)
    high = run_rollouts(
        env,
        k=4,
        model=OpenAIResponses(id="gpt-5.5", reasoning_effort="high"),
    )
    print(low)
    print(high)
    assert low.env_fingerprint == high.env_fingerprint
    assert low.policy_fingerprint != high.policy_fingerprint
    print(f"shared environment fingerprint: {low.env_fingerprint}")
    print(f"low policy fingerprint: {low.policy_fingerprint}")
    print(f"high policy fingerprint: {high.policy_fingerprint}")
    print(high.diff(low))
