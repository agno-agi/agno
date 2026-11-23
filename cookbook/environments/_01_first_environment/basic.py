"""
Your First Environment
======================

Run one agent several times against the same tasks and score every attempt.
The result is a pass-rate grid, not a claim based on one lucky sample.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Output and scorer
# ---------------------------------------------------------------------------
class Answer(BaseModel):
    value: int


def answer_matches(run, expected):
    return run.content.value == expected


# ---------------------------------------------------------------------------
# Agent and environment
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Return only the requested final integer in the typed field.",
)

environment = Environment(
    name="first-environment",
    agent=agent,
    tasks=(
        Task(input="What is 17 multiplied by 23?", expected=391, id="easy-product"),
        Task(
            input=(
                "Compute 2718281828459045 multiplied by 1618033988749895. "
                "Add the decimal digits of that product, multiply the digit sum "
                "by 131071, subtract the product remainder modulo 65521, and "
                "return the final integer."
            ),
            expected=20944939,
            id="chained-product-a",
        ),
        Task(
            input=(
                "Compute 3141592653589793 multiplied by 1414213562373095. "
                "Add the decimal digits of that product, multiply the digit sum "
                "by 104729, subtract the product remainder modulo 65537, and "
                "return the final integer."
            ),
            expected=16731173,
            id="chained-product-b",
        ),
    ),
    scorer=CodeScorer(answer_matches),
)


# ---------------------------------------------------------------------------
# Run rollouts
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
