"""
Trainer Loader - Basic
======================

Load the message arrays a trainer adapter would consume. The example stops at
the loader boundary: creating an SFT JSONL file is not a training run.
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


def load_message_rows(path: Path):
    return [json.loads(line)["messages"] for line in path.read_text().splitlines()]


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
)

env = Environment(
    name="trainer-loader-basic",
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

output_path = Path(__file__).parent / "data" / "generated" / "trainer_input.jsonl"


if __name__ == "__main__":
    result = run_rollouts(env, k=6)
    print(result)

    zone = result.learning_zone()
    if not zone.task_results:
        print("No learning-zone tasks; no trainer input was created.")
    else:
        report = to_sft_jsonl(zone, output_path)
        message_rows = load_message_rows(output_path)
        assert len(message_rows) == report.n_written
        print(f"loader received {len(message_rows)} message arrays")
        print("Stopped at the loader boundary; no training occurred.")
