"""
Critique and Revision - Basic
=============================

Constitutional-AI-style supervised phase: draft -> critique against one
written principle -> revise. The drafter answers tersely and decisively
(a realistic product persona that conflicts with the principle), the
critic judges the draft only against the principle at temperature 0, and
violating drafts are rewritten so the revision replaces the draft in the
output. Every row carries the principle, the critic's verdict, and
whether a revision happened, so downstream curation can trace exactly
why each response looks the way it does.
"""

import json
from pathlib import Path

from agno.agent import Agent, RunOutput
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Principle and Prompts
# ---------------------------------------------------------------------------
PRINCIPLE = (
    "State uncertainty honestly. When an answer depends on unknown, "
    "unknowable, or estimated quantities, say so explicitly and give a "
    "range or a stated assumption. Never present a guess as a fact."
)

# A mix of prompts that tempt overconfident guessing (Fermi estimates,
# predictions) and prompts with settled factual answers that should pass
# the critic untouched.
PROMPTS = [
    "How many piano tuners work in Chicago?",
    "What year will the first human land on Mars?",
    "What is the boiling point of water at sea level in Celsius?",
    "Will quantum computers break RSA-2048 within the next decade?",
    "Who wrote the novel 1984?",
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Critique(BaseModel):
    violates: bool = Field(
        ..., description="True if the draft violates the principle, else False"
    )
    critique: str = Field(
        ...,
        description=(
            "One or two sentences pointing at the exact claim that violates "
            "the principle, or stating why the draft complies"
        ),
    )


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
        "You are a critic. Judge the draft answer ONLY against the written "
        "principle you are given. Ignore style, length, and every other "
        "quality dimension. When the draft violates the principle, point at "
        "the exact claim that does so."
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


# ---------------------------------------------------------------------------
# Run Pipeline
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "critique_sft.jsonl"

    rows = []
    revised_count = 0

    for prompt in PROMPTS:
        draft_run: RunOutput = drafter.run(prompt)
        draft = draft_run.content.strip()

        critique_run: RunOutput = critic.run(
            f"PRINCIPLE:\n{PRINCIPLE}\n\nPROMPT:\n{prompt}\n\nDRAFT:\n{draft}"
        )
        verdict: Critique = critique_run.content

        response = draft
        if verdict.violates:
            revision_run: RunOutput = reviser.run(
                f"PRINCIPLE:\n{PRINCIPLE}\n\nPROMPT:\n{prompt}\n\n"
                f"DRAFT:\n{draft}\n\nCRITIQUE:\n{verdict.critique}\n\n"
                "Rewrite the draft so it satisfies the principle."
            )
            response = revision_run.content.strip()
            revised_count += 1

        rows.append(
            {
                "prompt": prompt,
                "response": response,
                "provenance": {
                    "principle": PRINCIPLE,
                    "violates": verdict.violates,
                    "critique": verdict.critique,
                    "revised": verdict.violates,
                },
            }
        )
        print(f"violates={verdict.violates} revised={verdict.violates} :: {prompt}")

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    pprint(rows[:2])
    n = len(rows)
    passed = n - revised_count
    print(
        f"wrote {n} rows to {out_path}, {revised_count} revised, {passed} passed through"
    )
