"""
Critique and Revision - Constitution Pairs
==========================================

Turn the draft -> critique -> revise loop into preference pairs: whenever
the critic finds a principle violation and the revision actually differs
from the draft, emit (chosen=revision, rejected=draft). This is the
supply chain into pairwise preference labeling - the script ends by
printing a paste-ready list literal in the exact EXAMPLES shape of
../_05_text_pairwise_preference/dpo_jury.py, so the jury can relabel the
pairs and check whether independent judges agree that the revision won.
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

# Weighted toward prompts that tempt overconfident guessing, since pairs
# are only emitted on violations; one settled-fact control is included.
PROMPTS = [
    "How many words does a typical person speak per day?",
    "What will the price of Bitcoin be at the end of next year?",
    "How long would it take to walk from Paris to Berlin?",
    "What is the chemical symbol for gold?",
    "How many stars are in the Milky Way?",
    "Will it rain in London on this day next year?",
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
    out_path = out_dir / "constitution_pairs.jsonl"

    pairs = []
    violations = 0
    identical_dropped = 0

    for prompt in PROMPTS:
        draft_run: RunOutput = drafter.run(prompt)
        draft = draft_run.content.strip()

        critique_run: RunOutput = critic.run(
            f"PRINCIPLE:\n{PRINCIPLE}\n\nPROMPT:\n{prompt}\n\nDRAFT:\n{draft}"
        )
        verdict: Critique = critique_run.content

        if not verdict.violates:
            print(f"violates=False pair=no :: {prompt}")
            continue
        violations += 1

        revision_run: RunOutput = reviser.run(
            f"PRINCIPLE:\n{PRINCIPLE}\n\nPROMPT:\n{prompt}\n\n"
            f"DRAFT:\n{draft}\n\nCRITIQUE:\n{verdict.critique}\n\n"
            "Rewrite the draft so it satisfies the principle."
        )
        revision = revision_run.content.strip()

        if revision == draft:
            identical_dropped += 1
            print(f"violates=True pair=no (revision identical) :: {prompt}")
            continue

        pairs.append(
            {
                "prompt": prompt,
                "chosen": revision,
                "rejected": draft,
                "provenance": {
                    "principle": PRINCIPLE,
                    "critique": verdict.critique,
                },
            }
        )
        print(f"violates=True pair=yes :: {prompt}")

    with out_path.open("w") as f:
        for pair in pairs:
            f.write(json.dumps(pair) + "\n")

    # Paste-ready handoff to the _05 jury. Chosen/rejected alternate between
    # answer slots a and b by index parity so the jury's position-bias
    # controls have something to work against.
    print("")
    print(
        "Paste-ready EXAMPLES entries for ../_05_text_pairwise_preference/dpo_jury.py:"
    )
    print("")
    literal_lines = ["["]
    for idx, pair in enumerate(pairs):
        pair_id = f"const-{idx + 1:02d}"
        if idx % 2 == 0:
            a, b = pair["chosen"], pair["rejected"]
        else:
            a, b = pair["rejected"], pair["chosen"]
        literal_lines.append("    dict(")
        literal_lines.append(f"        id={pair_id!r},")
        # Both sides of every pair were written by the drafting model, so
        # source_family carries its family and dpo_jury's self-preference
        # recusal benches the google juror on these pairs.
        literal_lines.append('        source_family="google",')
        literal_lines.append("        gold=None,")
        literal_lines.append(f"        prompt={pair['prompt']!r},")
        literal_lines.append(f"        a={a!r},")
        literal_lines.append(f"        b={b!r},")
        literal_lines.append("    ),")
    literal_lines.append("]")
    print("\n".join(literal_lines))
    print("")
    print(
        "This list drops into dpo_jury.py's EXAMPLES so the jury can relabel "
        "the pairs. Even-index pairs put the revision in slot a, odd-index "
        "pairs in slot b, so a jury that always prefers slot a is exposed."
    )

    n = len(pairs)
    print(
        f"wrote {n} pairs to {out_path} from {len(PROMPTS)} prompts: "
        f"{violations} violations, {identical_dropped} identical revisions dropped"
    )
