"""
Verified Dataset - Basic
========================

Run difficult typed tasks repeatedly, select rows with mixed binary outcomes,
and export only their passing conversations as portable SFT JSONL.
"""

from pathlib import Path

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts, to_sft_jsonl
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
    name="verified-dataset-basic",
    agent=agent,
    tasks=(
        Task(
            id="rounds-eight",
            input=(
                "Let a0=271828. For n=1 through 8, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_8."
            ),
            expected=6856135,
        ),
        Task(
            id="rounds-nine",
            input=(
                "Let a0=271828. For n=1 through 9, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_9."
            ),
            expected=7826798,
        ),
    ),
    scorer=CodeScorer(exact_integer),
)

output_path = Path(__file__).parent / "data" / "generated" / "verified.jsonl"


if __name__ == "__main__":
    result = run_rollouts(env, k=4, concurrency=4)
    print(result)

    zone = result.learning_zone()
    report = to_sft_jsonl(zone, output_path)
    print(f"learning-zone tasks: {len(zone.task_results)}")
    print(f"verified conversations: {report.n_written}")
    print(f"dataset: {output_path}")
    print("The file is a dataset; no training occurred.")
