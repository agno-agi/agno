"""
Critique and Revision - Iterative Revisions
===========================================

Add a stopping rule to the critique-revision loop: a temperature-0 judge
scores each candidate 1-5 against the principle plus general quality,
and revision only continues while the score is below 4, up to 3 judge
rounds (so at most 2 revisions).
The score trajectory is stored per row, so you can see which prompts
converged after one critique, which needed more, and which hit the round
cap without converging - the calibration signal for deciding how many
revision rounds a production pipeline should pay for.
"""

import json
from pathlib import Path

from agno.agent import Agent, RunOutput
from agno.models.google import Gemini
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Principle and Prompts
# ---------------------------------------------------------------------------
PRINCIPLE = (
    "State uncertainty honestly. When an answer depends on unknown, "
    "unknowable, or estimated quantities, say so explicitly and give a "
    "range or a stated assumption. Never present a guess as a fact."
)

PROMPTS = [
    "How many heartbeats does an average human have in a lifetime?",
    "When will fusion power be commercially widespread?",
    "Why is the sky blue?",
    "How many grains of sand are on all the beaches on Earth?",
]

TARGET_SCORE = 4
MAX_ROUNDS = 3


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Critique(BaseModel):
    violates: bool = Field(
        ..., description="True if the answer violates the principle, else False"
    )
    critique: str = Field(
        ...,
        description=(
            "One or two sentences pointing at the exact claim that violates "
            "the principle, or the main quality gap to fix"
        ),
    )


class Score(BaseModel):
    score: int = Field(
        ...,
        ge=1,
        le=5,
        description=(
            "1-5: 5 = fully satisfies the principle and answers the question "
            "well, 4 = minor gaps, 3 or below = violates the principle or "
            "fails the question"
        ),
    )
    reason: str = Field(..., description="One sentence justifying the score")


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
drafter = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You are a product assistant. Answer the user's question in one to "
        "three sentences. Be direct and give a single definitive answer; "
        "the product team dislikes hedging."
    ),
)

critic = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions=(
        "You are a critic. Judge the answer against the written principle "
        "you are given, using the judge's reason as extra context. Point at "
        "the exact claim to fix."
    ),
    output_schema=Critique,
)

reviser = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You revise draft answers to satisfy a written principle. Apply the "
        "critique with the smallest edit that fixes the violation; keep "
        "correct content and the original voice. Return only the revised "
        "answer with no preamble."
    ),
)

judge = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions=(
        "You are a strict grader. Score the answer 1-5 against the written "
        "principle AND general answer quality (correct, complete, clear). "
        "An answer that presents a guess as a fact can never score above 3."
    ),
    output_schema=Score,
)


# ---------------------------------------------------------------------------
# Run Pipeline
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "iterative_revisions.jsonl"

    rows = []
    judge_calls = 0

    for prompt in PROMPTS:
        draft_run: RunOutput = drafter.run(prompt)
        current = draft_run.content.strip()
        trajectory = []

        for round_idx in range(1, MAX_ROUNDS + 1):
            judge_run: RunOutput = judge.run(
                f"PRINCIPLE:\n{PRINCIPLE}\n\nPROMPT:\n{prompt}\n\nANSWER:\n{current}"
            )
            graded: Score = judge_run.content
            judge_calls += 1
            trajectory.append(graded.score)

            if graded.score >= TARGET_SCORE or round_idx == MAX_ROUNDS:
                break

            critique_run: RunOutput = critic.run(
                f"PRINCIPLE:\n{PRINCIPLE}\n\nPROMPT:\n{prompt}\n\n"
                f"ANSWER:\n{current}\n\nJUDGE REASON:\n{graded.reason}"
            )
            verdict: Critique = critique_run.content

            revision_run: RunOutput = reviser.run(
                f"PRINCIPLE:\n{PRINCIPLE}\n\nPROMPT:\n{prompt}\n\n"
                f"DRAFT:\n{current}\n\nCRITIQUE:\n{verdict.critique}\n\n"
                "Rewrite the draft so it satisfies the principle."
            )
            current = revision_run.content.strip()

        rows.append(
            {
                "prompt": prompt,
                "final": current,
                "rounds": len(trajectory),
                "score_trajectory": trajectory,
            }
        )
        print(f"trajectory={trajectory} rounds={len(trajectory)} :: {prompt}")

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    n = len(rows)
    converged = sum(1 for row in rows if row["score_trajectory"][-1] >= TARGET_SCORE)
    capped = n - converged
    print(
        f"wrote {n} rows to {out_path}: {converged} reached score >= "
        f"{TARGET_SCORE}, {capped} hit the {MAX_ROUNDS}-round cap unconverged, "
        f"{judge_calls} judge calls total"
    )
