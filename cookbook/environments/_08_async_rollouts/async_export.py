"""
Async rollouts - Export
=======================

Verify tasks asynchronously, select the learning-zone rows, and export only
their passing text attempts as conversational SFT JSONL.
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.environments import Environment, Task, arun_rollouts, ato_sft_jsonl
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class FinalInteger(BaseModel):
    value: int = Field(description="The final integer after every requested operation")


def exact_integer(run, expected) -> bool:
    return isinstance(run.content, FinalInteger) and run.content.value == expected


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    instructions="Calculate exactly. Return only the final integer in the response schema.",
    output_schema=FinalInteger,
)

env = Environment(
    name="async-export",
    agent=agent,
    tasks=(
        Task(
            id="export-edge-a",
            input=(
                "Multiply 2718281828459045 by 1618033988749895. Add the decimal "
                "digits of the product, multiply that digit sum by 131071, then "
                "subtract the product's remainder modulo 65521."
            ),
            expected=20944939,
        ),
        Task(
            id="export-edge-b",
            input=(
                "Multiply 3141592653589793 by 1414213562373095. Add the decimal "
                "digits of the product, multiply that digit sum by 65537, then "
                "subtract the product's remainder modulo 32749."
            ),
            expected=10481347,
        ),
    ),
    scorer=CodeScorer(exact_integer),
)


async def main() -> None:
    result = await arun_rollouts(env, k=4, concurrency=4)
    print(result)

    zone = result.learning_zone()
    output_path = Path(__file__).parent / "data" / "generated" / "learning_zone.jsonl"
    report = await ato_sft_jsonl(zone, output_path)
    print(f"learning-zone tasks: {len(zone.task_results)}")
    print(f"training rows written: {report.n_written}")
    print(f"dataset: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
