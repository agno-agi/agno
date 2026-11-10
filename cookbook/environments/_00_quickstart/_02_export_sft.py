"""
Export the Runs That Worked
===========================
The attempts that passed are, with no further labelling, a supervised
fine-tuning dataset. This is what the same rollout artifact gives you for
free once you have it.

Two selections stack here, and they answer different questions:

- results.learning_zone() selects TASKS whose attempts disagreed. A task the
  agent aces 8/8 carries no training signal (exporting it would overweight
  what the model already does, K-fold); a task at 0/8 has nothing to export.
  The tasks in between are where a trainer earns its keep.
- to_sft_jsonl(..., only_passed=True) then selects ATTEMPTS within those
  tasks: learning-zone tasks contain failures by construction, and a
  supervised file must not teach wrong answers.

The output is conversational-SFT JSONL -- {"messages": [{"role", "content"}]}
per line -- the common core that Tinker, Together, Fireworks and OpenAI all
accept. Scores and fingerprints ride in the <path>.meta.json sidecar, because
the file format itself has no room for provenance.
"""

from pathlib import Path

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts, to_sft_jsonl
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Create Environment
# ---------------------------------------------------------------------------


class Answer(BaseModel):
    value: int
    reasoning: str


def exact(run, expected):
    return run.content.value == expected


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"), output_schema=Answer
)

env = Environment(
    name="mental-math",
    agent=agent,
    tasks=(
        # One saturated anchor (no signal), two chained tasks hard enough that
        # attempts disagree -- the learning zone is where a trainer earns its keep.
        Task(input="What is 17 x 23?", expected=391),
        Task(
            input=(
                "Compute 2718281828459045 multiplied by 1618033988749895. Add the "
                "decimal digits of the product, multiply that digit sum by 131071, "
                "then subtract the product's remainder modulo 65521."
            ),
            expected=20944939,
        ),
        Task(
            input=(
                "Compute 3141592653589793 multiplied by 1414213562373095. Add the "
                "decimal digits of the product, multiply that digit sum by 65537, "
                "then subtract the product's remainder modulo 32749."
            ),
            expected=10481347,
        ),
    ),
    scorer=CodeScorer(exact),
)

_OUTPUT_DIR = Path(__file__).parent / "data" / "generated"

# ---------------------------------------------------------------------------
# Run, Select, Export
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = run_rollouts(env, k=8)
    print(results)
    print()

    zone = results.learning_zone()
    zone_ids = [task_result.task.id for task_result in zone.task_results]
    print(f"learning zone: {zone_ids}")

    if not zone.task_results:
        print(
            "no task disagreed across attempts, so there is nothing worth training on"
        )
        print("(make a task harder, or raise k, and the zone fills)")
    else:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        train_path = _OUTPUT_DIR / "train.jsonl"
        report = to_sft_jsonl(zone, train_path)

        print(f"wrote {report.n_written} conversations to {train_path}")
        print(f"skipped failed attempts: {report.n_skipped_failed}")
        print(f"skipped tool-bearing runs: {report.n_skipped_tool_runs}")
        print(f"skipped limit-hit runs: {report.n_skipped_limit_hit}")
        print(f"skipped runs with no text: {report.n_skipped_no_text}")
        print(f"dropped over cap: {report.n_dropped_over_cap}")
        print(f"provenance sidecar: {train_path}.meta.json")
