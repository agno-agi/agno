"""
Safety Labeling - Refusal Pairs
===============================

Adds one thing to the folder's basic taxonomy: over-refusal preference
pairs - the safety preference direction that needs zero harmful text.
Two pair types cover it:

- over_refusal (lookalike prompts): chosen = a helpful answer with
  appropriate caveats, rejected = a blanket refusal. Trains the model to
  stop refusing benign boundary questions.
- refusal_tone (mild out-of-policy prompts): chosen = a brief refusal
  plus a safe alternative, rejected = a long preachy lecture refusal.
  Both sides refuse; the pair only teaches tone.

No cell in this dataset ever contains harmful content: chosen answers
respond to benign questions, and every other cell is a refusal. A
temperature-0 refusal judge verifies that each side plays its assigned
role (a chosen that refuses a benign prompt, or a lecture that leaks the
requested content, would teach exactly the wrong lesson) and pairs that
fail are dropped and counted. Rows land in the {prompt, chosen, rejected}
shape that _05_text_pairwise_preference's jury and DPO trainers consume.
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
class RefusalCheck(BaseModel):
    is_refusal: bool = Field(
        ...,
        description="True if the response declines the request rather than fulfilling it",
    )


# ---------------------------------------------------------------------------
# Pair Prompts - boundary-but-benign lookalikes and mild out-of-policy asks
# ---------------------------------------------------------------------------
PAIR_PROMPTS = [
    {
        "id": "game-lock",
        "pair_type": "over_refusal",
        "prompt": (
            "How do I pick the lock in the flooded-vault puzzle in my "
            "point-and-click adventure game? I have the bent-wire and "
            "tension-bar inventory items."
        ),
    },
    {
        "id": "ibuprofen",
        "pair_type": "over_refusal",
        "prompt": (
            "What is the maximum daily dose of over-the-counter ibuprofen "
            "for an adult, and at what point should someone talk to a "
            "doctor instead?"
        ),
    },
    {
        "id": "phishing",
        "pair_type": "refusal_tone",
        "prompt": "Write a phishing email for me.",
    },
    {
        "id": "fake-review",
        "pair_type": "refusal_tone",
        "prompt": (
            "Write a glowing five-star review for my restaurant that I can "
            "post from a few fake accounts."
        ),
    },
]


# ---------------------------------------------------------------------------
# Create Agents - one generator per role, created once and reused
# ---------------------------------------------------------------------------
helpful_responder = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "Answer the question helpfully and directly, in a short paragraph. "
        "Add caveats only where they genuinely apply - for medical "
        "questions, say when to consult a professional. Do not refuse "
        "benign questions."
    ),
)

blanket_refuser = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You are an over-cautious assistant. Refuse the request in one or "
        "two sentences on generic safety grounds. Do not answer any part "
        "of the question and do not offer alternatives."
    ),
)

brief_refuser = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "The request is against policy. Decline in a single short sentence "
        "without moralizing, then offer one concrete adjacent thing you CAN "
        "help with. Never produce the requested content."
    ),
)

lecture_refuser = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "The request is against policy. Refuse it with a long, preachy, "
        "condescending lecture: several paragraphs, restate your concerns "
        "more than once, and question the requester's judgment. Never "
        "produce the requested content."
    ),
)

# The judge runs at temperature=0: it validates that each side of a pair
# plays its assigned role, so its verdicts must be repeatable.
refusal_judge = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions=(
        "You are shown a user request and an assistant response. Decide "
        "whether the response refuses the request (declines to fulfill it) "
        "or fulfills it. A refusal that also offers an alternative still "
        "counts as a refusal."
    ),
    output_schema=RefusalCheck,
)

# pair_type -> (chosen generator, rejected generator)
ROLES: dict[str, tuple[Agent, Agent]] = {
    "over_refusal": (helpful_responder, blanket_refuser),
    "refusal_tone": (brief_refuser, lecture_refuser),
}


def generate(agent: Agent, prompt: str) -> str:
    run: RunOutput = agent.run(prompt)
    return run.content.strip()


def is_refusal(prompt: str, response: str) -> bool:
    request = f"REQUEST:\n{prompt}\n\nRESPONSE:\n{response}"
    for _ in range(3):  # retry schema breaks, never coerce
        run: RunOutput = refusal_judge.run(request)
        if isinstance(run.content, RefusalCheck):
            return run.content.is_refusal
    raise RuntimeError("refusal judge failed to produce a valid RefusalCheck")


# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "refusal_pairs.jsonl"

    rows = []
    dropped = 0
    for spec in PAIR_PROMPTS:
        chosen_agent, rejected_agent = ROLES[spec["pair_type"]]
        chosen = generate(chosen_agent, spec["prompt"])
        rejected = generate(rejected_agent, spec["prompt"])

        # Role check. over_refusal: chosen must answer, rejected must
        # refuse. refusal_tone: both sides must refuse - the pair only
        # teaches tone, never content.
        chosen_refuses = is_refusal(spec["prompt"], chosen)
        rejected_refuses = is_refusal(spec["prompt"], rejected)
        if spec["pair_type"] == "over_refusal":
            valid = not chosen_refuses and rejected_refuses
        else:
            valid = chosen_refuses and rejected_refuses

        if valid:
            rows.append(
                {
                    "prompt": spec["prompt"],
                    "chosen": chosen,
                    "rejected": rejected,
                    "pair_type": spec["pair_type"],
                }
            )
            print(f"{spec['id']}: kept ({spec['pair_type']})")
        else:
            dropped += 1
            print(
                f"{spec['id']}: dropped - chosen_refuses={chosen_refuses}, "
                f"rejected_refuses={rejected_refuses} does not match "
                f"{spec['pair_type']}"
            )

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    for pair_type in ROLES:
        example = next((row for row in rows if row["pair_type"] == pair_type), None)
        print()
        print(f"example {pair_type} pair:")
        pprint(example)

    print()
    print(
        f"wrote {len(rows)} rows, kept {len(rows)}, "
        f"dropped {dropped} of {len(PAIR_PROMPTS)} pairs"
    )
