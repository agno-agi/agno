"""
Prompt Comparison - Basic
=========================

Measure two prompt environments separately and compare their summary values.
Prompt edits change environment identity, so EnvironmentDiff is not applicable.
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
        id="product-b",
        input=(
            "Compute 3141592653589793 times 2718281828459045. Add the decimal "
            "digits of that product, multiply the digit sum by 104729, subtract "
            "the product remainder modulo 65537, and return the final integer."
        ),
        expected=16756170,
    ),
)

terse_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Return the answer.",
)

checking_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions=(
        "Compute every intermediate value explicitly, re-check the product and "
        "modulo operation, then return the final answer."
    ),
)

terse_env = Environment(
    name="prompt-comparison-terse",
    agent=terse_agent,
    tasks=tasks,
    scorer=CodeScorer(exact_value),
)

checking_env = Environment(
    name="prompt-comparison-checking",
    agent=checking_agent,
    tasks=tasks,
    scorer=CodeScorer(exact_value),
)


if __name__ == "__main__":
    terse = run_rollouts(terse_env, k=4)
    checking = run_rollouts(checking_env, k=4)
    print(terse)
    print(checking)
    print(f"terse overall pass rate: {terse.pass_rate}")
    print(f"checking overall pass rate: {checking.pass_rate}")
    print(
        f"same environment fingerprint: {terse.env_fingerprint == checking.env_fingerprint}"
    )
    print("Prompt edits are separate environments; no EnvironmentDiff was computed.")
