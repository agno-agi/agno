"""
Saved Baselines - Async Save and Load
=====================================

Use the asynchronous twins when the surrounding application already owns the
event loop.
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.environments import Environment, EnvironmentRunResult, Task, arun_rollouts
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
    name="async-saved-baseline",
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
            id="product-b",
            input=(
                "Compute 3141592653589793 times 2718281828459045. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "104729, subtract the product remainder modulo 65537, and "
                "return the final integer."
            ),
            expected=16756170,
        ),
    ),
    scorer=CodeScorer(exact_value),
)

baseline_path = Path(__file__).parent / "data" / "generated" / "async_baseline.json"


async def main():
    result = await arun_rollouts(env, k=4)
    print(result)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    await result.asave(baseline_path)
    loaded = await EnvironmentRunResult.aload(baseline_path)
    assert loaded.summary() == result.summary()
    print(f"async round trip preserved {loaded.n_attempts} attempts")


if __name__ == "__main__":
    asyncio.run(main())
