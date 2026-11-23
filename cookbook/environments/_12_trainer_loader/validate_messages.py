"""
Trainer Loader - Validate Messages
==================================

Validate the portable intersection before a trainer-specific adapter reads it:
one top-level messages key, known roles, and non-empty text content.
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


def validate_sft_rows(path: Path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        assert set(row) == {"messages"}
        assert row["messages"]
        assert any(message["role"] == "user" for message in row["messages"])
        assert row["messages"][-1]["role"] == "assistant"
        for message in row["messages"]:
            assert set(message) == {"role", "content"}
            assert message["role"] in {"system", "user", "assistant"}
            assert isinstance(message["content"], str) and message["content"].strip()
    return rows


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
)

env = Environment(
    name="validate-trainer-messages",
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
            id="product-c",
            input=(
                "Compute 1414213562373095 times 1732050807568877. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "99991, subtract the product remainder modulo 32749, and "
                "return the final integer."
            ),
            expected=16568751,
        ),
    ),
    scorer=CodeScorer(exact_value),
)

output_path = Path(__file__).parent / "data" / "generated" / "validated.jsonl"


if __name__ == "__main__":
    result = run_rollouts(env, k=4)
    print(result)

    zone = result.learning_zone()
    if not zone.task_results:
        print("No learning-zone tasks; no rows were validated.")
    else:
        report = to_sft_jsonl(zone, output_path)
        rows = validate_sft_rows(output_path)
        assert len(rows) == report.n_written
        print(f"validated {len(rows)} portable message rows")
        print("Validation completed; no training occurred.")
