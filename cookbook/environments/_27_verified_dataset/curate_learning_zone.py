"""
Verified Dataset - Curate the learning zone
===========================================

Make curation explicit: retain only binary task rows whose observed pass rate
is strictly between zero and one, then asynchronously export passing attempts.
"""

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.environments import Environment, Task, arun_rollouts, ato_sft_jsonl
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class FinalInteger(BaseModel):
    value: int = Field(description="The final recurrence value")


def exact_integer(run, expected) -> bool:
    return isinstance(run.content, FinalInteger) and run.content.value == expected


agent = Agent(
    model=OpenAIResponses(
        id="gpt-5.5",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=3000,
    ),
    instructions="Compute the recurrence exactly and return only the final integer.",
    output_schema=FinalInteger,
)

env = Environment(
    name="curated-learning-zone",
    agent=agent,
    tasks=(
        Task(id="easy-anchor", input="Multiply 17 by 23.", expected=391),
        Task(
            id="rounds-eight",
            input=(
                "Let a0=271828. For n=1 through 8, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_8."
            ),
            expected=6856135,
        ),
        Task(
            id="rounds-ten",
            input=(
                "Let a0=271828. For n=1 through 10, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_10."
            ),
            expected=542370,
        ),
    ),
    scorer=CodeScorer(exact_integer),
)

output_path = Path(__file__).parent / "data" / "generated" / "curated.jsonl"


async def main() -> None:
    result = await arun_rollouts(env, k=4, concurrency=4)
    print(result)

    partial_ids = [
        task_result.task.id
        for task_result in result.task_results
        if task_result.pass_rate is not None and 0 < task_result.pass_rate < 1
    ]
    zone = result.learning_zone()
    report = await ato_sft_jsonl(zone, output_path)
    print(f"strict partial-rate tasks: {partial_ids}")
    print(f"verified conversations: {report.n_written}")
    print("Export completed; no training occurred.")


if __name__ == "__main__":
    asyncio.run(main())
