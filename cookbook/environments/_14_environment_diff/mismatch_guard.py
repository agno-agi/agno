"""
Environment Diff - Mismatch Guard
=================================

Editing instructions changes the environment fingerprint. The diff refuses the
comparison because a policy delta cannot be separated from a prompt delta.
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

baseline_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Return the computed integer.",
)

edited_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Work carefully and verify every intermediate arithmetic step.",
)

baseline_env = Environment(
    name="environment-mismatch-guard",
    agent=baseline_agent,
    tasks=tasks,
    scorer=CodeScorer(exact_value),
)

edited_env = Environment(
    name="environment-mismatch-guard",
    agent=edited_agent,
    tasks=tasks,
    scorer=CodeScorer(exact_value),
)


if __name__ == "__main__":
    baseline = run_rollouts(baseline_env, k=4)
    edited = run_rollouts(edited_env, k=4)
    print(baseline)
    print(edited)
    try:
        edited.diff(baseline)
    except MismatchError as error:
        print(f"comparison rejected as expected: {error}")
