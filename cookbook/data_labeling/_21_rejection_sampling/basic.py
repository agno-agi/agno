"""
Rejection Sampling - Basic
==========================

Generate K candidate reasoning traces per problem with a teacher model, then
keep only the traces whose final answer matches a programmatically verified
gold. The verifier is pure code (integer equality), so every kept trace has
a verified-correct final answer - no judge involved. The reasoning text
itself is not checked: a trace with flawed reasoning that lands on the right
integer is kept, the known false-positive mode of answer-only rejection
sampling. This is the data type behind verified-reasoning recipes: sample,
check, keep.

Each problem here has an integer gold answer that was verified by hand and
by a script before being committed.
"""

import json
from pathlib import Path

from agno.agent import Agent, RunOutput
from pydantic import BaseModel, Field
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class Solution(BaseModel):
    reasoning: str = Field(..., description="step by step reasoning")
    final_answer: int = Field(..., description="the final integer answer alone")


# ---------------------------------------------------------------------------
# Problems
# ---------------------------------------------------------------------------
# Every gold below is programmatically verifiable and was checked before
# being committed. A wrong gold silently poisons the kept traces.
PROBLEMS = [
    {
        "id": "p1",
        "prompt": (
            "A bakery makes 12 trays of muffins per day, with 6 muffins per "
            "tray. Each day 15 muffins are set aside for staff and the rest "
            "are sold. How many muffins are sold across 5 days?"
        ),
        "gold": 285,
    },
    {
        "id": "p2",
        "prompt": "How many ways can you choose 3 books from 7 distinct books?",
        "gold": 35,
    },
    {
        "id": "p3",
        "prompt": (
            "What does this Python program print?\n\n"
            "x = 0\n"
            "for i in range(1, 6):\n"
            "    if i % 2 == 0:\n"
            "        x += i * i\n"
            "    else:\n"
            "        x -= i\n"
            "print(x)"
        ),
        "gold": 11,
    },
    {
        "id": "p4",
        "prompt": (
            "A train travels 180 km at 60 km/h, then another 120 km at "
            "40 km/h. How many minutes does the whole trip take?"
        ),
        "gold": 360,
    },
    {
        "id": "p5",
        "prompt": "How many 3-digit numbers have all three digits distinct?",
        "gold": 648,
    },
    {
        "id": "p6",
        "prompt": (
            "What does this Python program print?\n\n"
            'words = ["red", "green", "blue", "cyan"]\n'
            "total = 0\n"
            "for w in words:\n"
            "    if len(w) > 3:\n"
            "        total += len(w)\n"
            "print(total)"
        ),
        "gold": 13,
    },
]

K = 4  # samples per problem


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Default temperature so the K samples vary. No session memory is configured,
# so repeated .run() calls are independent samples of the same prompt.
teacher = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "Solve the problem step by step. Show your full reasoning, then "
        "give the final integer answer."
    ),
    output_schema=Solution,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "verified_traces.jsonl"

    rows = []
    dropped = 0
    problems_passed = 0

    for problem in PROBLEMS:
        correct = 0
        for sample_index in range(K):
            run: RunOutput = teacher.run(problem["prompt"])
            solution: Solution = run.content
            # The verifier is pure code: exact match against the gold.
            if solution.final_answer == problem["gold"]:
                correct += 1
                rows.append(
                    {
                        "prompt": problem["prompt"],
                        "reasoning": solution.reasoning,
                        "final_answer": solution.final_answer,
                        "sample_index": sample_index,
                    }
                )
            else:
                dropped += 1
        if correct > 0:
            problems_passed += 1
        print(f"problem {problem['id']}: {correct}/{K} samples correct")

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print()
    print("example kept trace:")
    pprint(rows[0] if rows else None)

    total = len(PROBLEMS) * K
    pass_at_k = problems_passed / len(PROBLEMS)
    print()
    print(
        f"pass@{K}: {problems_passed}/{len(PROBLEMS)} problems "
        f"with at least one correct sample ({pass_at_k:.2f})"
    )
    print(
        f"wrote {len(rows)} rows, kept {len(rows)}, dropped {dropped} of {total} samples"
    )
