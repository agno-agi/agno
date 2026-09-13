"""
Prompt Comparison - Instruction Detail
=======================================

Compare a short instruction with a detailed verification checklist, then show
that the environment-fingerprint guard rejects a policy-style diff.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer, MismatchError
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
        id="product-c",
        input=(
            "Compute 1414213562373095 times 1732050807568877. Add the decimal "
            "digits of that product, multiply the digit sum by 99991, subtract "
            "the product remainder modulo 32749, and return the final integer."
        ),
        expected=16568751,
    ),
)

short_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Solve the arithmetic problem.",
)

detailed_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions=(
        "First compute the exact product. Independently sum its decimal digits. "
        "Then compute the multiplier and remainder terms, subtract in the stated "
        "order, and verify the final integer before responding."
    ),
)

short_env = Environment(
    name="instruction-detail",
    agent=short_agent,
    tasks=tasks,
    scorer=CodeScorer(exact_value),
)

detailed_env = Environment(
    name="instruction-detail",
    agent=detailed_agent,
    tasks=tasks,
    scorer=CodeScorer(exact_value),
)


if __name__ == "__main__":
    short = run_rollouts(short_env, k=4)
    detailed = run_rollouts(detailed_env, k=4)
    print(short)
    print(detailed)
    print(f"short prompt pass rate: {short.pass_rate}")
    print(f"detailed prompt pass rate: {detailed.pass_rate}")
    try:
        detailed.diff(short)
    except MismatchError as error:
        print(f"diff rejected because instructions changed: {error}")
