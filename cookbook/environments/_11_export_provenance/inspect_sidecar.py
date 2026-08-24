"""
Export Provenance - Inspect the Sidecar
=======================================

Export rows and provenance entries share deterministic order. Validate the
sidecar against the retained result, then zip the trusted pair for inspection.
The sidecar records provenance but does not authenticate the JSONL bytes.
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
    name="inspect-export-sidecar",
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

output_path = Path(__file__).parent / "data" / "generated" / "inspected.jsonl"
sidecar_path = Path(str(output_path) + ".meta.json")


if __name__ == "__main__":
    output_path.unlink(missing_ok=True)
    sidecar_path.unlink(missing_ok=True)

    result = run_rollouts(env, k=6)
    print(result)

    zone = result.learning_zone()
    if not zone.task_results:
        assert not output_path.exists() and not sidecar_path.exists()
        print("No learning-zone tasks; make the tasks harder before exporting.")
    else:
        report = to_sft_jsonl(zone, output_path)
        conversations = [
            json.loads(line) for line in output_path.read_text().splitlines()
        ]
        sidecar = json.loads(sidecar_path.read_text())
        assert len(conversations) == len(sidecar["lines"]) == report.n_written
        assert zone.env_fingerprint is not None
        assert zone.policy_fingerprint is not None
        assert sidecar["env_fingerprint"] == zone.env_fingerprint
        assert sidecar["policy_fingerprint"] == zone.policy_fingerprint
        assert sidecar["options"] == {"only_passed": True}
        task_results = {
            str(task_result.task.id): task_result for task_result in zone.task_results
        }
        for row, provenance in zip(conversations, sidecar["lines"]):
            task_result = task_results[str(provenance["task_id"])]
            attempt = task_result.attempts[provenance["attempt_index"]]
            assert attempt.score is not None and attempt.score.passed
            assert attempt.score.value == provenance["score"]
            assistant = row["messages"][-1]["content"]
            print(
                f"task={provenance['task_id']} attempt={provenance['attempt_index']} "
                f"score={provenance['score']} assistant={assistant}"
            )
        print(
            "Provenance validated against this in-memory result. Keep the JSONL and "
            "sidecar together in a trusted store; the sidecar has no JSONL digest."
        )
