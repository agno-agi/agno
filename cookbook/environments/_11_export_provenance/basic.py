"""
Export Provenance - Basic
=========================

The portable SFT file contains messages only. Verification provenance is kept
in a sidecar so consumers that reject extra JSONL keys still accept the data.
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
    name="export-provenance-basic",
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
                "Compute 3141592653589793 times 1414213562373095. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "65537, subtract the product remainder modulo 32749, and "
                "return the final integer."
            ),
            expected=10481347,
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
        sidecar_path = Path(str(output_path) + ".meta.json")
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        print(f"dataset rows: {report.n_written}")
        print(f"sidecar rows: {len(sidecar['lines'])}")
        print(f"environment fingerprint: {sidecar['env_fingerprint']}")
        print(f"policy fingerprint: {sidecar['policy_fingerprint']}")
