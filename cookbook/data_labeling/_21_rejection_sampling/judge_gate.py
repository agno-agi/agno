"""
Rejection Sampling - Judge Gate
===============================

Best-of-N for prompts with no programmatic verifier. A generator samples N
candidates per open-ended prompt; a temperature-0 judge scores each one
against a rubric. The top-scoring candidate is kept only if it clears an
absolute bar (score >= 4) - argmax alone is not enough, because the best of
N bad samples is still bad. Prompts whose best candidate misses the bar are
dropped entirely.

Unlike a scoring report, the judge here gates what enters the dataset. All
N scores are written alongside each kept row as provenance.
"""

import json
from pathlib import Path

from agno.agent import Agent, RunOutput
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class Draft(BaseModel):
    text: str = Field(
        ..., description="The response text, following every constraint in the prompt"
    )


class Verdict(BaseModel):
    score: int = Field(
        ...,
        ge=1,
        le=5,
        description="Quality score from 1 (unusable) to 5 (excellent)",
    )
    reason: str = Field(..., description="One-sentence justification for the score")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
PROMPTS = [
    ("Write a two-sentence product description for a solar-powered camping lantern."),
    (
        "Explain the difference between a process and a thread to a junior "
        "developer, in under 80 words."
    ),
    (
        # Adversarial constraint prompt. The drop path fires whenever every
        # candidate for a prompt misses the score bar.
        "Write one grammatically correct English sentence of exactly 10 "
        "words in which every word begins with the letter 'x'."
    ),
    (
        "Write a coherent paragraph of 30 to 40 words about winter mornings "
        "that does not contain the letter 'e' anywhere."
    ),
]

N = 3  # candidates per prompt
SCORE_BAR = 4  # minimum score for the argmax candidate to be kept


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
judge_instructions = """\
Score the candidate response against its prompt:
1 - unusable: wrong, off-topic, or ignores the prompt
2 - poor: partially addresses the prompt or breaks a stated constraint
3 - acceptable: correct but flat, generic, or slightly imprecise
4 - good: correct, clear, follows every constraint
5 - excellent: correct, precise, well-phrased, follows every constraint

Check stated constraints explicitly before scoring: count words and
sentences when a limit is given, and scan for forbidden words or letters.
For a forbidden-letter constraint, go word by word and name every violating
word in your reason. A response that violates any explicit constraint
scores at most 2, no matter how well written it is. Use the full scale.
Reserve 5 for genuinely excellent responses.
"""


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
# Generator samples at default temperature so the N candidates vary.
generator = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "Write a short, high-quality response. Follow every constraint in "
        "the prompt exactly."
    ),
    output_schema=Draft,
)

# Judge runs at temperature=0 so the gate is as stable as possible.
judge = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions=judge_instructions,
    output_schema=Verdict,
)


def build_judge_input(prompt: str, candidate: str) -> str:
    return f"Prompt:\n{prompt}\n\nCandidate response:\n{candidate}"


# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "judge_gated.jsonl"

    rows = []
    dropped = 0

    for i, prompt in enumerate(PROMPTS, start=1):
        candidates = []
        verdicts = []
        for _ in range(N):
            gen_run: RunOutput = generator.run(prompt)
            draft: Draft = gen_run.content
            judge_run: RunOutput = judge.run(build_judge_input(prompt, draft.text))
            verdict: Verdict = judge_run.content
            candidates.append(draft.text)
            verdicts.append(verdict)

        all_scores = [v.score for v in verdicts]
        # Deterministic argmax: ties resolve to the earliest candidate.
        best = max(range(N), key=lambda j: all_scores[j])

        if all_scores[best] >= SCORE_BAR:
            rows.append(
                {
                    "prompt": prompt,
                    "chosen": candidates[best],
                    "chosen_score": all_scores[best],
                    "all_scores": all_scores,
                    "judge_reason": verdicts[best].reason,
                }
            )
            print(
                f"prompt {i}: scores {all_scores} -> kept sample {best} "
                f"(score {all_scores[best]})"
            )
        else:
            dropped += 1
            print(
                f"prompt {i}: scores {all_scores} -> dropped, best score "
                f"{all_scores[best]} < {SCORE_BAR}: {verdicts[best].reason}"
            )

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print()
    print("example kept row:")
    pprint(rows[0] if rows else None)

    print()
    print(
        f"wrote {len(rows)} rows, kept {len(rows)} of {len(PROMPTS)} prompts, "
        f"dropped {dropped}"
    )
