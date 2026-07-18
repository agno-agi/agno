"""
Persona-Driven Generation - Gold-Answer Math Problems
=====================================================

Personas condition math problem generation: each problem is grounded in one
persona's working world (a farmer's feed rates, a photographer's shot
counts), which varies surface form without touching the arithmetic. The
problem shape is pinned to unit-rate multiplication - exactly two whole
numbers in the text, answer = their product - so a pure-Python check
re-derives each gold as the product of the two numbers in the text. Rows
that fail the check are dropped and counted; only verified rows are
written. The
output feeds ../_21_rejection_sampling/, which needs trustworthy golds.
"""

import json
import re
from pathlib import Path

from agno.agent import Agent, RunOutput
from pydantic import BaseModel, Field
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Personas (hand-written so this file runs standalone)
# ---------------------------------------------------------------------------
PERSONAS = [
    {
        "occupation": "dairy farmer",
        "expertise_level": "intermediate",
        "communication_style": "plainspoken and practical",
        "current_concern": "rising feed costs per cow",
    },
    {
        "occupation": "emergency room nurse",
        "expertise_level": "novice",
        "communication_style": "hurried and direct",
        "current_concern": "restocking supplies across night shifts",
    },
    {
        "occupation": "food truck owner",
        "expertise_level": "expert",
        "communication_style": "chatty and numbers-minded",
        "current_concern": "ingredient budgeting for the lunch rush",
    },
    {
        "occupation": "wedding photographer",
        "expertise_level": "intermediate",
        "communication_style": "warm and detail-oriented",
        "current_concern": "estimating editing hours per event",
    },
    {
        "occupation": "long-haul truck driver",
        "expertise_level": "novice",
        "communication_style": "direct and skeptical of jargon",
        "current_concern": "fuel spend per leg of a route",
    },
    {
        "occupation": "middle school librarian",
        "expertise_level": "expert",
        "communication_style": "patient and precise",
        "current_concern": "shelving capacity for a new book order",
    },
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class MathProblem(BaseModel):
    problem: str = Field(
        ...,
        description=(
            "A unit-rate word problem grounded in the persona's working world. "
            "The text must contain exactly two whole numbers written in digits "
            "(each between 2 and 99) and no other digits anywhere. The question "
            "asks for the total, which is the product of the two numbers. The "
            "answer itself must not appear in the text."
        ),
    )
    answer: int = Field(
        ...,
        description="The gold answer: the product of the two numbers in the problem",
    )
    reasoning: str = Field(
        ..., description="One or two sentences deriving the answer from the two numbers"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
problem_agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You write unit-rate multiplication word problems for a given persona. "
        "Ground the scenario in the persona's occupation and current concern. "
        "Hard constraints: the problem text contains exactly two whole numbers "
        "written in digits, each between 2 and 99; no other digits appear "
        "anywhere in the text (no years, prices, decimals, or times in digits); "
        "the answer is the product of those two numbers; the answer does not "
        "appear in the problem text."
    ),
    output_schema=MathProblem,
)


# ---------------------------------------------------------------------------
# Verify (pure Python: re-derive the gold from the problem text)
# ---------------------------------------------------------------------------
# The check proves the stated answer is the product of the two numbers in
# the text and that every prompt constraint the code can see holds. It
# cannot check question semantics: a problem whose question deviates from
# the constrained product shape (e.g. asks for a sum) would still pass.
# Closing that gap needs a judge or teacher disagreement - see
# _21_rejection_sampling.
def verify(problem: str, answer: int) -> tuple[bool, str]:
    numbers = [int(m) for m in re.findall(r"\d+", problem)]
    if len(numbers) != 2:
        return (
            False,
            f"expected exactly 2 numbers in problem text, found {len(numbers)}",
        )
    if not all(2 <= n <= 99 for n in numbers):
        return False, f"numbers {numbers} outside the required 2-99 range"
    product = numbers[0] * numbers[1]
    if product != answer:
        return (
            False,
            f"stated answer {answer} != {numbers[0]} * {numbers[1]} = {product}",
        )
    return True, "ok"


def build_request(persona: dict) -> str:
    lines = [
        "Persona:",
        f"- occupation: {persona['occupation']}",
        f"- expertise_level: {persona['expertise_level']}",
        f"- communication_style: {persona['communication_style']}",
        f"- current_concern: {persona['current_concern']}",
        "",
        "Write one unit-rate multiplication word problem set in this persona's world.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Run Generation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "math_problems.jsonl"

    rows = []
    dropped = 0
    for persona in PERSONAS:
        run: RunOutput = problem_agent.run(build_request(persona))
        candidate = run.content
        ok, reason = verify(candidate.problem, candidate.answer)
        if not ok:
            dropped += 1
            print(f"dropped ({persona['occupation']}): {reason}")
            continue
        rows.append(
            {
                "problem": candidate.problem,
                "answer": candidate.answer,
                "persona_occupation": persona["occupation"],
            }
        )

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    pprint(rows[:2])
    kept = len(rows)
    print(
        f"wrote {kept} rows to {out_path}, kept {kept}, dropped {dropped} "
        f"of {len(PERSONAS)} generated (product re-derived in code for every kept answer)"
    )
