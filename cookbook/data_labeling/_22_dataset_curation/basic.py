"""
Dataset Curation - Judge Quality Gate
=====================================

Filter an SFT dataset row by row with an LLM judge. Each (instruction,
response) pair is scored 1-5 against a fixed rubric; rows scoring >= 4 are
kept and written out with their score and reason attached, so every surviving
row carries the provenance of why it survived.

Input is data/sample_rows.jsonl (a committed fixture with a deliberate
quality mix). Point input_path at any generated dataset to gate it the same
way.
"""

import json
from pathlib import Path
from typing import Literal

from agno.agent import Agent, RunOutput
from agno.models.google import Gemini
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class RowVerdict(BaseModel):
    score: int = Field(
        ...,
        ge=1,
        le=5,
        description="Row quality on a 1-5 scale where 5 is excellent",
    )
    verdict: Literal["keep", "drop"] = Field(
        ..., description="keep if score >= 4, otherwise drop"
    )
    reason: str = Field(
        ..., description="One short sentence naming the deciding criterion"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a quality gate for supervised fine-tuning data. Score each
(instruction, response) row on a 1-5 scale against three criteria:

- Clarity: the response is specific and well organized, not vague filler.
- Factual correctness: every checkable claim in the response is true.
- Self-containedness: the row makes sense on its own. It must not depend on
  missing context (e.g. "the passage above"), end truncated mid-thought, or
  merely echo the instruction back.

5 - excellent on all three criteria
4 - good: minor imperfections, trainable as-is
3 - acceptable surface form but one real defect (vague, incomplete)
2 - poor: factually wrong, truncated, or fails a criterion outright
1 - unusable

Verdict rule: keep if and only if score >= 4, otherwise drop. Keep the
reason to one short sentence naming the deciding criterion.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
judge = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions=instructions,
    output_schema=RowVerdict,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def build_input(row: dict) -> str:
    return f"Instruction:\n{row['instruction']}\n\nResponse:\n{row['response']}"


if __name__ == "__main__":
    input_path = Path(__file__).parent / "data" / "sample_rows.jsonl"
    output_dir = Path(__file__).parent / "data" / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "curated.jsonl"

    rows = [
        json.loads(line) for line in input_path.read_text().splitlines() if line.strip()
    ]

    kept = 0
    dropped = 0
    print("row  score  verdict  instruction / reason")
    print("-" * 75)
    with output_path.open("w") as f:
        for i, row in enumerate(rows):
            v = None
            for _ in range(3):  # retry schema breaks, never coerce
                run: RunOutput = judge.run(build_input(row))
                if isinstance(run.content, RowVerdict):
                    v = run.content
                    break
            if v is None:
                raise RuntimeError("judge failed to produce a valid RowVerdict")
            preview = row["instruction"][:52]
            print(f"{i:>3}  {v.score:>5}  {v.verdict:<7}  {preview}")
            print(f"                     -> {v.reason}")
            # The gate is the score bar; the verdict field is provenance. A
            # judge emitting verdict="keep" with score < 4 does not pass.
            if v.verdict == "keep" and v.score >= 4:
                f.write(
                    json.dumps(
                        {
                            "instruction": row["instruction"],
                            "response": row["response"],
                            "score": v.score,
                            "reason": v.reason,
                        }
                    )
                    + "\n"
                )
                kept += 1
            else:
                dropped += 1

    print("-" * 75)
    print(
        f"wrote {kept} rows to {output_path.relative_to(Path(__file__).parent)}: "
        f"kept {kept}, dropped {dropped} of {len(rows)}"
    )
