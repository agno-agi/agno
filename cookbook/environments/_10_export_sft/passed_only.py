"""
Export SFT - Passed Attempts Only
=================================

The learning zone selects tasks, not attempts. Exporting with the default
only_passed=True removes the failed attempts inside those selected tasks.
"""

import json
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
    name="export-passed-only",
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
            id="product-d",
            input=(
                "Compute 2236067977499789 times 2449489742783178. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "524287, subtract the product remainder modulo 99991, and "
                "return the final integer."
            ),
            expected=76998482,
        ),
    ),
    scorer=CodeScorer(exact_value),
)

output_path = Path(__file__).parent / "data" / "generated" / "passed.jsonl"


if __name__ == "__main__":
    result = run_rollouts(env, k=6)
    print(result)

    zone = result.learning_zone()
    if not zone.task_results:
        print("No learning-zone tasks; nothing safe to export.")
    else:
        n_passed = sum(task_result.n_passed for task_result in zone.task_results)
        report = to_sft_jsonl(zone, output_path)
        rows = [json.loads(line) for line in output_path.read_text().splitlines()]
        assert report.n_written == n_passed == len(rows)
        print(f"learning-zone passing attempts: {n_passed}")
        print(f"failed attempts excluded: {report.n_skipped_failed}")
        print(f"validated JSONL rows: {len(rows)}")
