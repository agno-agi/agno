"""
Verified Dataset - Export manifest
==================================

Export passing learning-zone conversations, inspect the provenance sidecar,
and write a compact manifest with the dataset hash and selected task ids.
"""

import hashlib
import json
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
    name="verified-dataset-manifest",
    agent=agent,
    tasks=(
        Task(
            id="rounds-nine",
            input=(
                "Let a0=271828. For n=1 through 9, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_9."
            ),
            expected=7826798,
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

generated_dir = Path(__file__).parent / "data" / "generated"
dataset_path = generated_dir / "verified_with_manifest.jsonl"
manifest_path = generated_dir / "manifest.json"


if __name__ == "__main__":
    result = run_rollouts(env, k=4, concurrency=4)
    print(result)

    zone = result.learning_zone()
    report = to_sft_jsonl(zone, dataset_path)
    sidecar_path = Path(str(dataset_path) + ".meta.json")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    dataset_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    manifest = {
        "format_version": 1,
        "dataset": dataset_path.name,
        "sha256": dataset_hash,
        "n_rows": report.n_written,
        "task_ids": [task_result.task.id for task_result in zone.task_results],
        "env_fingerprint": sidecar["env_fingerprint"],
        "policy_fingerprint": sidecar["policy_fingerprint"],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"verified conversations: {report.n_written}")
    print(f"dataset sha256: {dataset_hash}")
    print(f"manifest: {manifest_path}")
    print("Artifacts are ready for a separate trainer; no training occurred.")
