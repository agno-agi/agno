"""
Export SFT - Basic
==================

Run repeated attempts, keep the tasks in the learning zone, and export only
their passing text conversations. This creates a dataset; it does not train.
"""

from pathlib import Path

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts, to_sft_jsonl
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
    name="export-sft-basic",
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

output_path = Path(__file__).parent / "data" / "generated" / "train.jsonl"


if __name__ == "__main__":
    result = run_rollouts(env, k=4)
    print(result)

    zone = result.learning_zone()
    if not zone.task_results:
        print("No learning-zone tasks; make the tasks harder before exporting.")
    else:
        report = to_sft_jsonl(zone, output_path)
        print(f"wrote {report.n_written} passing conversations to {output_path}")
        print(f"skipped failed attempts: {report.n_skipped_failed}")
        print("The JSONL is a dataset only; no training occurred.")
