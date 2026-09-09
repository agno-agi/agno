"""
Environment Fingerprints
========================

Stamp the measuring setup and the sampled policy on every result. A scorer,
task, or prompt edit changes the environment fingerprint; a model change
changes the policy fingerprint.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int


def answer_matches(run, expected):
    return run.content.value == expected


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Return only the requested final integer in the typed field.",
)

environment = Environment(
    name="fingerprinted-arithmetic",
    agent=agent,
    tasks=(
        Task(input="What is 37 multiplied by 41?", expected=1517, id="easy-product"),
        Task(
            input=(
                "Compute 2718281828459045 multiplied by 1618033988749895. "
                "Add its decimal digits, multiply that sum by 131071, subtract "
                "the product remainder modulo 65521, and return the result."
            ),
            expected=20944939,
            id="chained-product-a",
        ),
        Task(
            input=(
                "Compute 3141592653589793 multiplied by 1414213562373095. "
                "Add its decimal digits, multiply that sum by 104729, subtract "
                "the product remainder modulo 65537, and return the result."
            ),
            expected=16731173,
            id="chained-product-b",
        ),
    ),
    scorer=CodeScorer(answer_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
    print()

    summary = results.summary()
    print(f"environment fingerprint: {summary['env_fingerprint']}")
    print(f"policy fingerprint: {summary['policy_fingerprint']}")
    print(f"environment matches result: {environment.env_matches(results)}")
