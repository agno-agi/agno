"""
Instruction Generation - Self-Instruct
======================================

Bootstrap new training instructions from a small hand-written seed pool.
Each round shows the generator a few seeds as few-shot examples and asks
for novel instructions that differ in task type and domain. Candidates are
deduplicated against the seeds and against already-accepted instructions
with a word-set Jaccard filter, so the pool grows without collapsing onto
near-duplicates.
"""

import json
from pathlib import Path

from agno.agent import Agent, RunOutput
from pydantic import BaseModel, Field
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Seed Instructions
# ---------------------------------------------------------------------------
SEEDS = [
    {
        "id": "seed-01",
        "text": "Rewrite this sentence in a formal tone: 'gonna need those numbers asap'.",
    },
    {
        "id": "seed-02",
        "text": "Extract every date mentioned in the following paragraph and list them in ISO format.",
    },
    {
        "id": "seed-03",
        "text": "Explain how a binary search works to someone who has never programmed.",
    },
    {
        "id": "seed-04",
        "text": "Plan a three-day study schedule for an exam on European history.",
    },
    {
        "id": "seed-05",
        "text": "Write a Python function that returns the median of a list of numbers.",
    },
    {
        "id": "seed-06",
        "text": "Classify this support ticket as billing, technical, or account: 'I was charged twice this month'.",
    },
    {
        "id": "seed-07",
        "text": "Summarize the plot of Romeo and Juliet in exactly three sentences.",
    },
    {
        "id": "seed-08",
        "text": "Compare renting versus buying a home for someone moving cities every two years.",
    },
]

SEEDS_PER_ROUND = 3
ROUNDS = 2
CANDIDATES_PER_ROUND = 5
JACCARD_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class NewInstructions(BaseModel):
    instructions: list[str] = Field(
        ...,
        description="Novel, self-contained task instructions, each on a different task type and domain",
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
generator = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You write novel training instructions for a language model. "
        "Given a few example instructions, produce new instructions that "
        "differ from the examples in BOTH task type and domain. Each "
        "instruction must be self-contained and answerable without external "
        "files or links. Vary the opening verbs."
    ),
    output_schema=NewInstructions,
)


# ---------------------------------------------------------------------------
# Dedupe Filter (stdlib)
# ---------------------------------------------------------------------------
def word_set(text: str) -> set:
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower())
    return set(cleaned.split())


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_near_duplicate(candidate: str, existing: list) -> bool:
    candidate_words = word_set(candidate)
    return any(
        jaccard(candidate_words, word_set(text)) >= JACCARD_THRESHOLD
        for text in existing
    )


# ---------------------------------------------------------------------------
# Run Generation
# ---------------------------------------------------------------------------
def build_prompt(seed_batch: list) -> str:
    lines = ["Example instructions:"]
    for seed in seed_batch:
        lines.append(f"- {seed['text']}")
    lines.append("")
    lines.append(
        f"Write {CANDIDATES_PER_ROUND} novel instructions that differ in "
        "task type and domain from the examples above."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "instructions.jsonl"

    accepted_texts = [seed["text"] for seed in SEEDS]
    rows = []
    dropped = 0

    for round_idx in range(ROUNDS):
        seed_batch = SEEDS[
            round_idx * SEEDS_PER_ROUND : (round_idx + 1) * SEEDS_PER_ROUND
        ]
        seed_ids = [seed["id"] for seed in seed_batch]

        run: RunOutput = generator.run(build_prompt(seed_batch))
        candidates = run.content.instructions[:CANDIDATES_PER_ROUND]

        for candidate in candidates:
            candidate = candidate.strip()
            if is_near_duplicate(candidate, accepted_texts):
                dropped += 1
                continue
            accepted_texts.append(candidate)
            rows.append(
                {"instruction": candidate, "seed_ids": seed_ids, "round": round_idx + 1}
            )

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    pprint(rows[:3])
    kept = len(rows)
    print(f"wrote {kept} rows to {out_path}, kept {kept}, dropped {dropped}")
