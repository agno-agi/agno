"""
Prompt Comparison - Format Constraint
=====================================

Compare terse-answer and explanation-bearing instructions under the same typed
schema. Format instructions are prompt content and therefore environment state.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int
    reasoning: str


def exact_value(run, expected):
    return run.content.value == expected


tasks = (
    Task(
        id="product-a",
        input=(
            "Compute 2718281828459045 times 1618033988749895. Add the decimal "
            "digits of that product, multiply the digit sum by 131071, subtract "
            "the product remainder modulo 65521, and return the final integer."
        ),
        expected=20944939,
    ),
    Task(
        id="product-d",
        input=(
            "Compute 2236067977499789 times 2449489742783178. Add the decimal "
            "digits of that product, multiply the digit sum by 524287, subtract "
            "the product remainder modulo 99991, and return the final integer."
        ),
        expected=76998482,
    ),
)

concise_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Put only a short calculation note in reasoning.",
)

auditable_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions=(
        "In reasoning, record the product, digit sum, multiplied digit sum, and "
        "modulo remainder before returning the final value."
    ),
)

concise_env = Environment(
    name="format-constraint-concise",
    agent=concise_agent,
    tasks=tasks,
    scorer=CodeScorer(exact_value),
)

auditable_env = Environment(
    name="format-constraint-auditable",
    agent=auditable_agent,
    tasks=tasks,
    scorer=CodeScorer(exact_value),
)


if __name__ == "__main__":
    concise = run_rollouts(concise_env, k=4)
    auditable = run_rollouts(auditable_env, k=4)
    print(concise)
    print(auditable)
    print(f"concise pass rate: {concise.pass_rate}")
    print(f"auditable pass rate: {auditable.pass_rate}")
    print(
        f"environment fingerprints differ: {concise.env_fingerprint != auditable.env_fingerprint}"
    )
